// The Python half of the browser kernel. It mirrors `KernelSession` in
// products/notebooks/backend/sandbox/kernel/bootstrap.py, so a cell behaves the same in the browser
// as in a sandbox: the same last-expression rule, the same result-frame choice, the same envelope
// shape, and the same ClickHouse-style type names the charts read.
// Kept as a string because the worker bundle is built by esbuild, which has no raw-file loader.
// The source must not contain a backtick or a dollar-brace pair.
export const BROWSER_KERNEL_SESSION_SOURCE = String.raw`
import io
import sys
import json
import uuid
import base64
import warnings
import linecache
import traceback
import contextlib
from collections import OrderedDict

import duckdb
import pandas as pd
from pyodide.code import eval_code_async

_DEFAULT_PREVIEW_ROWS = 50
_STREAM_CAP_CHARS = 32_768
_CELL_CAP_CHARS = 10_000
_MEDIA_MAX_FIGURES = 8
_MEDIA_TOTAL_CAP_CHARS = 4_000_000
_SNAPSHOT_MAX_OBJECTS = 200
_SNAPSHOT_MAX_COLUMNS = 100
_RESULT_CACHE_SIZE = 32
_INTERRUPTED_MESSAGE = "Run interrupted."

# plt.show() has nothing to open in a worker. The session collects open figures after each run instead.
warnings.filterwarnings("ignore", message="FigureCanvasAgg is non-interactive")


def _display(*objects):
    """Print each object, so notebook code that calls display() works outside IPython."""
    for obj in objects:
        print(obj.to_string(max_rows=20) if isinstance(obj, pd.DataFrame) else obj)


def _error_message(exc):
    # str(KeyError("x")) quotes its message, which reads as a typo in front of the user.
    detail = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
    return f"{type(exc).__name__}: {detail}"


def _truncate_stream(text):
    if len(text) <= _STREAM_CAP_CHARS:
        return text
    return f"{text[:_STREAM_CAP_CHARS]}\n… [output truncated: exceeded {_STREAM_CAP_CHARS // 1024} KB]"


def _column_type_name(dtype):
    if pd.api.types.is_bool_dtype(dtype):
        return "Bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "Int64"
    if pd.api.types.is_float_dtype(dtype):
        return "Float64"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "DateTime"
    return "String"


def _safe_cell(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _json_rows(df):
    try:
        rows = json.loads(df.to_json(orient="values", date_format="iso"))
    except (OverflowError, UnicodeDecodeError, ValueError, TypeError):
        rows = [[_safe_cell(cell) for cell in row] for row in df.itertuples(index=False, name=None)]
    return [
        [f"{cell[:_CELL_CAP_CHARS]}…" if isinstance(cell, str) and len(cell) > _CELL_CAP_CHARS else cell for cell in row]
        for row in rows
    ]


def _frame_from_columns(columns, types, values):
    """Build a pandas frame from column-major JSON values and their HogQL type names."""
    type_by_name = {name: type_name for name, type_name in (types or [])}
    data = {}
    for column, column_values in zip(columns, values):
        series = pd.Series(list(column_values), dtype="object")
        type_name = str(type_by_name.get(column) or "")
        base = type_name.replace("Nullable(", "").rstrip(")")
        try:
            if base.startswith("DateTime") or base.startswith("Date"):
                series = pd.to_datetime(series, errors="coerce", utc=True, format="ISO8601")
            elif base.startswith("Int") or base.startswith("UInt"):
                series = pd.to_numeric(series, errors="coerce").astype("Int64")
            elif base.startswith("Float") or base.startswith("Decimal"):
                series = pd.to_numeric(series, errors="coerce").astype("float64")
            elif base == "Bool":
                series = series.astype("boolean")
            else:
                series = series.infer_objects()
        except Exception:
            series = series.infer_objects()
        data[column] = series
    return pd.DataFrame(data, columns=list(columns))


class BrowserKernelSession:
    def __init__(self):
        self.user_ns = {"__name__": "__main__", "__builtins__": __builtins__, "display": _display}
        self.duck = duckdb.connect()
        # name -> ("output" | "input", frame, node_id, input_key)
        self._registered = {}
        self._bound_variables = set()
        self._results = OrderedDict()
        # Input frames the page fetched from PostHog, keyed by the upstream run, until a run reads them.
        self._staged = {}
        self._plt = None

    # Runs --------------------------------------------------------------------------------------

    async def run_node(self, payload):
        payload = payload.to_py() if hasattr(payload, "to_py") else payload
        result = await self._execute_node(payload)
        self._reap_stale_registrations()
        result["frames"] = self._catalog_snapshot()
        return json.dumps(result)

    async def _execute_node(self, payload):
        node_type = str(payload.get("node_type") or "python")
        node_id = str(payload.get("node_id") or "")
        preview_rows = int(payload.get("page_limit") or _DEFAULT_PREVIEW_ROWS)
        if node_type == "python":
            self._bind_variables(payload.get("variables") or {})
        try:
            self._register_inputs(payload.get("inputs") or [], node_type=node_type)
        except Exception as exc:
            detail = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            return {"status": "error", "error": f"Input registration failed: {detail}"}
        if node_type == "duckdb":
            return self._run_duckdb_node(payload, node_id, preview_rows)
        return await self._run_python_node(payload, node_id, preview_rows)

    async def _run_python_node(self, payload, node_id, preview_rows):
        code = str(payload.get("code") or "")
        output_name = str(payload.get("output_name") or "")
        ns_ids_before = {name: id(value) for name, value in self.user_ns.items()} if output_name else {}
        plt = self._pyplot_if_loaded()
        if plt is not None:
            plt.close("all")
        # Lets a traceback quote the lines of the cell that raised.
        linecache.cache["<cell>"] = (len(code), None, code.splitlines(True), "<cell>")
        stdout, stderr = io.StringIO(), io.StringIO()
        value, error = None, None
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                value = await eval_code_async(code, globals=self.user_ns, filename="<cell>")
            except KeyboardInterrupt as exc:
                error = exc
            except BaseException as exc:
                error = exc
                traceback.print_exception(type(exc), exc, self._user_traceback(exc.__traceback__), file=sys.stderr)
        media, omitted = self._collect_media()
        out = _truncate_stream(stdout.getvalue())
        err = _truncate_stream(stderr.getvalue())
        if omitted:
            err += f"\n[{omitted} figure(s) omitted: over the media size cap]"
        if isinstance(error, KeyboardInterrupt):
            return {"status": "interrupted", "stdout": out, "stderr": err, "error": _INTERRUPTED_MESSAGE, "media": media}
        if error is not None:
            return {"status": "error", "stdout": out, "stderr": err, "error": _error_message(error), "media": media}

        result_df = self._result_frame(output_name, value)
        if output_name:
            if result_df is not None:
                self.user_ns[output_name] = result_df
                self._register_duck(output_name, result_df, origin="output", node_id=node_id)
            else:
                self._unregister_duck(output_name)
                err += self._missed_save_note(output_name, ns_ids_before)
        envelope = self._envelope(result_df, preview_rows)
        envelope.update({"stdout": out, "stderr": err, "media": media})
        return envelope

    def _run_duckdb_node(self, payload, node_id, preview_rows):
        output_name = str(payload.get("output_name") or "")
        params = payload.get("variables") or {}
        try:
            code = str(payload.get("code") or "")
            relation = self.duck.sql(code, params=params) if params else self.duck.sql(code)
            result_df = relation.df() if relation is not None else None
        except Exception as exc:
            return {"status": "error", "error": _error_message(exc)}
        if output_name:
            if result_df is not None:
                self.user_ns[output_name] = result_df
                self._register_duck(output_name, result_df, origin="output", node_id=node_id)
            else:
                self.user_ns.pop(output_name, None)
                self._unregister_duck(output_name)
        return self._envelope(result_df, preview_rows)

    def _envelope(self, df, preview_rows):
        envelope = {"status": "ok", "columns": [], "types": [], "row_count": 0, "first_page": [], "has_more": False}
        if df is None:
            return envelope
        result_id = str(uuid.uuid4())
        self._results[result_id] = df
        while len(self._results) > _RESULT_CACHE_SIZE:
            self._results.popitem(last=False)
        envelope.update(
            {
                "columns": [str(column) for column in df.columns],
                "types": [[str(column), _column_type_name(dtype)] for column, dtype in zip(df.columns, df.dtypes)],
                "row_count": int(len(df)),
                "first_page": _json_rows(df.head(preview_rows)),
                "has_more": len(df) > preview_rows,
                "result_id": result_id,
            }
        )
        return envelope

    def _user_traceback(self, tb):
        # Skip the frames of this module and of pyodide's own eval machinery, so the traceback
        # starts at the user's cell the way IPython's does.
        while tb is not None and tb.tb_frame.f_code.co_filename != "<cell>":
            tb = tb.tb_next
        return tb

    def _bind_variables(self, variables):
        bound = set()
        for name, value in dict(variables).items():
            if isinstance(name, str) and name.isidentifier():
                self.user_ns[name] = value
                bound.add(name)
        for stale in self._bound_variables - bound:
            self.user_ns.pop(stale, None)
        self._bound_variables = bound

    def _register_inputs(self, inputs, node_type):
        bind_pandas = node_type == "python"
        for spec in inputs:
            name = spec["name"]
            kind = spec.get("kind")
            if kind == "hogql":
                key = spec.get("key")
                registration = self._registered.get(name)
                if registration is not None and registration[0] == "input" and registration[3] == key:
                    frame = registration[1]
                else:
                    frame = self._take_staged(key)
                    if frame is None:
                        raise KeyError(f"the rows for '{name}' were not loaded. Run the cell again")
                    self._register_duck(name, frame, origin="input", node_id=spec.get("node_id"), key=key)
                if bind_pandas:
                    self.user_ns[name] = frame.copy()
            elif kind == "local":
                if name in self.user_ns:
                    frame = self.user_ns[name]
                    if isinstance(frame, pd.DataFrame):
                        existing = self._registered.get(name)
                        self._register_duck(name, frame, origin="output", node_id=existing[2] if existing else None)
                    else:
                        self._unregister_duck(name)
                        if node_type == "duckdb":
                            raise TypeError(f"'{name}' is not a dataframe in the kernel (it is {type(frame).__name__})")
                else:
                    self._unregister_duck(name)
                    raise KeyError(f"'{name}' is not in the browser kernel. Run the cell that creates it first")
            else:
                raise ValueError(f"unknown input kind '{kind}' for '{name}'")

    # Staged inputs: rows the page fetched from PostHog, waiting for the run that reads them.

    def stage_input(self, key, columns, types, values):
        columns = list(columns.to_py() if hasattr(columns, "to_py") else columns)
        types = [list(pair) for pair in (types.to_py() if hasattr(types, "to_py") else types)]
        values = values.to_py() if hasattr(values, "to_py") else values
        self._staged[str(key)] = _frame_from_columns(columns, types, values)

    def has_input(self, key):
        return any(registration[0] == "input" and registration[3] == key for registration in self._registered.values())

    def _take_staged(self, key):
        return self._staged.pop(str(key), None)

    # DuckDB registry -----------------------------------------------------------------------------

    def _register_duck(self, name, frame, origin, node_id=None, key=None):
        self._unregister_duck(name)
        self.duck.register(name, frame)
        self._registered[name] = (origin, frame, node_id, key)

    def _unregister_duck(self, name):
        try:
            self.duck.unregister(name)
        except Exception:
            pass
        self._registered.pop(name, None)

    def _reap_stale_registrations(self):
        for name, registration in list(self._registered.items()):
            if registration[0] == "output" and not isinstance(self.user_ns.get(name), pd.DataFrame):
                self._unregister_duck(name)

    def _catalog_snapshot(self):
        try:
            columns_by_name = {}
            for schema_name, table_name, column_name, data_type in self.duck.execute(
                "SELECT schema_name, table_name, column_name, data_type FROM duckdb_columns() "
                "WHERE NOT internal ORDER BY table_name, column_index"
            ).fetchall():
                columns = columns_by_name.setdefault(str(table_name), [])
                if len(columns) < _SNAPSHOT_MAX_COLUMNS:
                    columns.append([str(column_name), str(data_type)])
            table_sizes = {
                str(table_name): (int(size) if size is not None else None)
                for table_name, size in self.duck.execute(
                    "SELECT table_name, estimated_size FROM duckdb_tables() WHERE NOT internal"
                ).fetchall()
            }
        except BaseException:
            return None
        frames = []
        for name in sorted(columns_by_name):
            registration = self._registered.get(name)
            if registration is not None:
                entry = {
                    "name": name,
                    "columns": columns_by_name[name],
                    "kind": "frame",
                    "row_count": int(len(registration[1])),
                    "node_id": registration[2],
                    "origin": registration[0],
                }
            elif name in table_sizes:
                entry = {
                    "name": name,
                    "columns": columns_by_name[name],
                    "kind": "table",
                    "row_count": table_sizes[name],
                    "row_count_is_estimate": True,
                }
            else:
                entry = {"name": name, "columns": columns_by_name[name], "kind": "view", "row_count": None}
            frames.append(entry)
            if len(frames) >= _SNAPSHOT_MAX_OBJECTS:
                break
        return frames

    def frames(self):
        return json.dumps(self._catalog_snapshot() or [])

    # Paging --------------------------------------------------------------------------------------

    def page(self, result_id, offset, limit):
        df = self._results.get(str(result_id))
        if df is None:
            return json.dumps({"missing": True})
        window = df.iloc[int(offset) : int(offset) + int(limit)]
        return json.dumps(
            {
                "columns": [str(column) for column in df.columns],
                "types": [[str(column), _column_type_name(dtype)] for column, dtype in zip(df.columns, df.dtypes)],
                "rows": _json_rows(window),
                "has_more": int(offset) + int(limit) < len(df),
                "total": int(len(df)),
            }
        )

    def read_frame(self, name, offset, limit):
        """One page of a named frame, in the shape the widget frame endpoint returns."""
        registration = self._registered.get(str(name))
        frame = registration[1] if registration is not None else self.user_ns.get(str(name))
        if not isinstance(frame, pd.DataFrame):
            return json.dumps({"missing": True})
        offset, limit = int(offset), int(limit)
        window = frame.iloc[offset : offset + limit]
        total = int(len(frame))
        next_offset = offset + len(window) if offset + len(window) < total else None
        return json.dumps(
            {
                "name": str(name),
                "columns": [{"name": str(column), "type": _column_type_name(dtype)} for column, dtype in zip(frame.columns, frame.dtypes)],
                "rows": _json_rows(window),
                "totalRowCount": total,
                "includedRowCount": int(len(window)),
                "offset": offset,
                "nextOffset": next_offset,
                "truncated": next_offset is not None,
            }
        )

    # Helpers -------------------------------------------------------------------------------------

    def _missed_save_note(self, output_name, ns_ids_before):
        created = sorted(
            name
            for name, value in self.user_ns.items()
            if not name.startswith("_") and isinstance(value, pd.DataFrame) and ns_ids_before.get(name) != id(value)
        )
        if not created:
            return ""
        names = ", ".join(f"'{name}'" for name in created)
        return (
            f"\n[nothing was saved as '{output_name}': this run created {names}. "
            f"Assign the dataframe to '{output_name}' or end the cell with it as the last expression.]"
        )

    def _result_frame(self, output_name, last_expression):
        if isinstance(last_expression, pd.DataFrame):
            return last_expression
        if isinstance(last_expression, pd.Series):
            return last_expression.to_frame()
        if output_name:
            candidate = self.user_ns.get(output_name)
            if isinstance(candidate, pd.DataFrame):
                return candidate
        return None

    def _pyplot_if_loaded(self):
        # matplotlib is a large download, so it loads only once a cell imports it. The worker
        # sets MPLBACKEND=Agg before any cell runs, so the figure stays headless either way.
        if self._plt is None and "matplotlib.pyplot" in sys.modules:
            self._plt = sys.modules["matplotlib.pyplot"]
        return self._plt

    def _collect_media(self):
        plt = self._pyplot_if_loaded()
        if plt is None:
            return [], 0
        media, omitted, budget = [], 0, _MEDIA_TOTAL_CAP_CHARS
        for number in plt.get_fignums():
            buffer = io.BytesIO()
            plt.figure(number).savefig(buffer, format="png", bbox_inches="tight")
            data = base64.b64encode(buffer.getvalue()).decode()
            if len(media) >= _MEDIA_MAX_FIGURES or len(data) > budget:
                omitted += 1
                continue
            budget -= len(data)
            media.append({"mime_type": "image/png", "data": data})
        plt.close("all")
        return media, omitted


_ph_browser = BrowserKernelSession()
`
