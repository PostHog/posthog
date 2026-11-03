import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from products.exports.backend.facade.api import InvalidExportContext, save_export_asset_content_from_file

from ..facade import api
from ..logic.traces.trace_export import (
    MAX_TRACE_EXPORT_MEGABYTES,
    TRACE_EXPORT_DATABASE_FALLBACK_BYTES,
    InvalidTraceExportRequestError,
    TraceExportTooLargeError,
)

if TYPE_CHECKING:
    from products.exports.backend.facade.api import ExportedAsset


def export_trace_json(asset: "ExportedAsset") -> None:
    """Writes the trace export file. Failures the user can act on raise `InvalidExportContext`, which is not retried."""
    if asset.created_by is None:
        raise InvalidExportContext("The trace export configuration is invalid.", reportable=True)
    file_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as export_file:
            file_path = export_file.name
            api.write_trace_export(asset.team, asset.created_by, asset.export_context or {}, export_file)
        save_export_asset_content_from_file(
            asset=asset, file_path=file_path, max_database_bytes=TRACE_EXPORT_DATABASE_FALLBACK_BYTES
        )
    except InvalidTraceExportRequestError as error:
        raise InvalidExportContext("The trace export configuration is invalid.", reportable=True) from error
    except api.TraceNotFoundError as error:
        raise InvalidExportContext("This trace is no longer available.") from error
    except api.TraceExportForbiddenError as error:
        raise InvalidExportContext("You no longer have access to this trace.") from error
    except TraceExportTooLargeError as error:
        raise InvalidExportContext(
            f"This trace is larger than {MAX_TRACE_EXPORT_MEGABYTES} MB, so it can't be exported."
        ) from error
    finally:
        if file_path is not None:
            Path(file_path).unlink(missing_ok=True)
