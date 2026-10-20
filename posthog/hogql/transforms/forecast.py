import math
import time
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

import numpy as np

from posthog.hogql.errors import QueryError
from posthog.hogql.functions.forecast import ForecastCall

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from onnxruntime import InferenceSession

    from posthog.models.team import Team

# Timestral-28M constants, from the model config and TimestralForecaster defaults.
PATCH = 32
BLOCK_PATCHES = 32
# Older history barely changes a forecast, and attention cost grows with the context.
MAX_CONTEXT = 8192
MIN_SCALE = 1e-6
CAP_K = 1e4
EXTREME = 1e30
# Positions of p10, p50 and p90 among the 21 quantile levels 0.01, 0.05, 0.1, ..., 0.95, 0.99.
P10, P50, P90 = 2, 10, 18
# Threads one ONNX session may use for one operator. Web processes share the pod's cores, so a forecast
# must not take every core.
ONNX_INTRA_OP_THREADS = 2
# Context points per ONNX run and per query. They bound the memory of one run and the CPU time of one query.
BATCH_POINTS = 32768
MAX_TOTAL_POINTS = 262144


def validate_forecast_access(team: "Team") -> None:
    if not feature_enabled_or_false(
        "hogql-forecast",
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.id)}},
        send_feature_flag_events=False,
    ):
        raise QueryError("forecast is not available for this project yet.")


def _ffill(x: np.ndarray, mask: np.ndarray) -> np.ndarray:
    idx = np.maximum.accumulate(np.where(mask, np.arange(x.shape[-1]), 0), axis=-1)
    return np.take_along_axis(x, idx, axis=-1)


def _clamp_nonfinite(v: np.ndarray) -> np.ndarray:
    finite = np.isfinite(v)
    hi = np.where(finite, v, -np.inf).max(-1, keepdims=True)
    lo = np.where(finite, v, np.inf).min(-1, keepdims=True)
    v = np.where(v == np.inf, hi, np.where(v == -np.inf, lo, v))
    return np.where(np.isinf(v), 0.0, v)


def _refine(q: np.ndarray, context: np.ndarray, mask: np.ndarray, loc0: np.ndarray, scale0: np.ndarray) -> np.ndarray:
    """Re-denormalize each horizon patch after the first with the statistics of the context plus the earlier medians.

    This is the advancing refine frame the model was trained in (timestral `_refine_block`).
    """
    rows, n = q.shape[0], q.shape[1] // PATCH
    if n <= 1:
        return q
    loc0, scale0 = loc0.astype(np.float64)[:, None], scale0.astype(np.float64)[:, None]
    sinh_median = (q[..., P50].reshape(rows, n, PATCH) - loc0[..., None]) / scale0[..., None]
    w = mask.astype(np.float64)
    cnt = w.sum(-1)
    mean = (w * context).sum(-1) / np.maximum(cnt, 1.0)
    m2 = (w * (context - mean[:, None]) ** 2).sum(-1)
    offset = mean
    clip = np.finfo(np.float32).max ** 0.5 / 1e3
    locs, scales = [], []
    for h in range(n):
        scale = np.maximum(np.sqrt(np.maximum(m2 / np.maximum(cnt - 1.0, 1.0), 0.0)), MIN_SCALE)
        locs.append(mean)
        scales.append(scale)
        folded = np.clip(sinh_median[:, h] * scale[:, None] + (mean - offset)[:, None], -clip, clip) + offset[:, None]
        b_mean = folded.mean(-1)
        delta = b_mean - mean
        mean = mean + delta * PATCH / (cnt + PATCH)
        m2 = m2 + ((folded - b_mean[:, None]) ** 2).sum(-1) + delta**2 * cnt * PATCH / (cnt + PATCH)
        cnt = cnt + PATCH
    loc_j, scale_j = np.stack(locs, 1).astype(q.dtype), np.stack(scales, 1).astype(q.dtype)
    loc_j[:, 0], scale_j[:, 0] = loc0[:, 0], scale0[:, 0]
    loc_j, scale_j = np.repeat(loc_j, PATCH, -1), np.repeat(scale_j, PATCH, -1)
    sinh_norm = (q - loc0[..., None].astype(q.dtype)) / scale0[..., None].astype(q.dtype)
    return _clamp_nonfinite(sinh_norm * scale_j[..., None] + loc_j[..., None]).astype(q.dtype)


class Forecaster:
    """Timestral inference around the ONNX block from bin/export_forecast_model.py, matching TimestralForecaster.forecast."""

    def __init__(self, session: "InferenceSession") -> None:
        self.session = session

    def forecast(self, values: np.ndarray, horizon: int) -> np.ndarray:
        """(B, T) series, NaN for missing, to (B, horizon, 21) quantiles."""
        mask = np.isfinite(values)
        x = np.where(mask, values, 0.0).astype(np.float32)
        b = x.shape[0]
        # Average with the flipped forecast of -x. The mirrored rows run in the same batch.
        raw = self._forecast_raw(np.concatenate([x, -x]), np.concatenate([mask, mask]), horizon)
        q = 0.5 * (raw[:b] - raw[b:, :, ::-1])
        nonnegative = mask.any(-1) & ((x >= 0) | ~mask).all(-1)
        return np.where(nonnegative[:, None, None], np.maximum(q, 0.0), q)

    def _forecast_raw(self, x: np.ndarray, mask: np.ndarray, horizon: int) -> np.ndarray:
        x, mask = _ffill(x, mask)[:, -MAX_CONTEXT:], mask[:, -MAX_CONTEXT:]
        pad = (-x.shape[-1]) % PATCH
        x, mask = np.pad(x, ((0, 0), (pad, 0))), np.pad(mask, ((0, 0), (pad, 0)))
        context, context_mask = x, mask
        blocks: list[np.ndarray] = []
        remaining = math.ceil(horizon / PATCH)
        while remaining > 0:
            patches = min(BLOCK_PATCHES, remaining)
            feed = {"context": x, "mask": mask, "horizon": np.zeros(patches, np.float32)}
            q, loc0, scale0 = self.session.run(None, feed)
            blocks.append(_refine(q, x.astype(np.float64), mask, loc0, scale0))
            remaining -= patches
            # Later blocks read this block's median as context.
            median = blocks[-1][..., P50]
            x = np.concatenate([x, np.where(np.abs(median) < EXTREME, median, 0.0).astype(np.float32)], -1)[
                :, -MAX_CONTEXT:
            ]
            mask = np.concatenate([mask, np.ones_like(median, dtype=bool)], -1)[:, -MAX_CONTEXT:]
        q = np.concatenate(blocks, 1)[:, :horizon]
        # Keep every quantile within CAP_K context scales of the observed range.
        w = context_mask.astype(np.float64)
        cnt = w.sum(-1)
        mean = (w * context).sum(-1) / np.maximum(cnt, 1.0)
        std = np.sqrt((w * (context - mean[:, None]) ** 2).sum(-1) / np.maximum(cnt - 1.0, 1.0))
        cap = (np.maximum(std, MIN_SCALE) * CAP_K).astype(np.float32)[:, None, None]
        hi = np.where(context_mask.any(-1), np.where(context_mask, context, -np.inf).max(-1), 0.0)[:, None, None]
        lo = np.where(context_mask.any(-1), np.where(context_mask, context, np.inf).min(-1), 0.0)[:, None, None]
        return np.clip(q, lo - cap, hi + cap)


@cache
def _model() -> Forecaster:
    import onnxruntime  # noqa: PLC0415 — keeps onnxruntime's native runtime off the HogQL import path

    path = Path(settings.HOGQL_FORECAST_MODEL_PATH)
    if not path.exists():
        raise QueryError("forecast is not set up on this server. Run bin/export_forecast_model.py to create the model.")
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = ONNX_INTRA_OP_THREADS
    options.inter_op_num_threads = 1
    return Forecaster(onnxruntime.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"]))


def _batches(series: dict[int, list[float]]) -> list[list[int]]:
    """Row indexes in batches of at most BATCH_POINTS context points.

    Rows are sorted by length, so each batch pads its shorter rows by little.
    """
    batches: list[list[int]] = []
    for i in sorted(series, key=lambda i: len(series[i])):
        if not batches or (len(batches[-1]) + 1) * len(series[i]) > BATCH_POINTS:
            batches.append([])
        batches[-1].append(i)
    return batches


def evaluate_forecast(spec: ForecastCall, values: list[object], deadline: float) -> list[object]:
    if any(value is not None and not isinstance(value, list | tuple) for value in values):
        raise QueryError("forecast values must be an array of numbers.")
    series = {
        i: [np.nan if x is None else x for x in value[-MAX_CONTEXT:]]
        for i, value in enumerate(values)
        if isinstance(value, list | tuple) and len(value) >= 2
    }
    if sum(len(s) for s in series.values()) > MAX_TOTAL_POINTS:
        raise QueryError(
            f"forecast reads at most {MAX_TOTAL_POINTS} values across all rows. Use fewer rows or shorter histories."
        )
    out: list[object] = [([], [], []) for _ in values]
    for batch in _batches(series):
        if time.monotonic() >= deadline:
            raise QueryError("forecast exceeded its time limit. Use fewer rows or shorter histories.")
        # NaN is missing, so shorter series are padded on the left.
        width = len(series[batch[-1]])
        context = np.full((len(batch), width), np.nan)
        try:
            for row, i in enumerate(batch):
                context[row, width - len(series[i]) :] = series[i]
        except (TypeError, ValueError) as error:
            raise QueryError("forecast values must be an array of numbers.") from error
        bands = _model().forecast(context, spec.horizon)[..., [P10, P50, P90]]
        for row, i in enumerate(batch):
            out[i] = tuple(band.tolist() for band in bands[row].T)
    return out
