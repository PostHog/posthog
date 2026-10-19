#!/usr/bin/env python3
"""Export the Timestral forecasting network to ONNX for the HogQL `forecast` function.

Runs at image build time only (see the export-forecast-model stage in the Dockerfile), so the
runtime image needs onnxruntime and numpy, not torch. The graph covers one univariate block:
scaling, the transformer, and the quantile head. posthog/hogql/transforms/forecast.py runs the
block loop, the refine step, and the mirrored pass around it in numpy.

Usage: export_forecast_model.py <output.onnx>
"""

import sys

import torch
import torch.nn.functional as F
from timestral import TimestralForecaster
from timestral.layers import Attention
from timestral.masks import build_forecast_positions, build_forecast_time_mask
from timestral.scaler import apply_affine_asinh_masked, denormalize_quantiles

MODEL = "mistralai/Timestral-28M"
REVISION = "49b26409ac87b5935539a5d8ffe7f397b720db47"

_time_forward = Attention.forward


def _forward(self: Attention, x: torch.Tensor, mask: object, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    if self.is_time:
        return _time_forward(self, x, mask, cos, sin)
    # Every row is its own series, so a variate query reads only itself, and attention returns v.
    # Project v in the time layout, with the fused QKV rows reordered from (head_dim, heads) to
    # (heads, head_dim). This skips an attention that grows with the square of the batch, and two transposes.
    d, hd, nh = self.embed_dim, self.head_dim, self.num_heads
    order = (2 * d + torch.arange(hd)[None, :] * nh + torch.arange(nh)[:, None]).reshape(-1)
    bias = self.wQKV.bias[order] if self.wQKV.bias is not None else None
    out = F.linear(x, self.wQKV.weight[order], bias)
    if self._gate is not None:
        out = out * self._gate(x).sigmoid()
    return self.wO(out)


Attention.forward = _forward


class Block(torch.nn.Module):
    """(R, T) context and mask to anchor-frame quantiles (R, H * patch_size, Q) and the anchor loc and scale."""

    def __init__(self, forecaster: TimestralForecaster) -> None:
        super().__init__()
        self.m = forecaster.model.eval()

    def forward(
        self, context: torch.Tensor, mask: torch.Tensor, horizon: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        c = self.m.config
        ps = c.patch_size
        rows, t = context.shape
        ll, h = t // ps, horizon.shape[0]
        # Causal float64 Welford statistics. Each patch takes the statistics at its last step.
        x, w = context.double(), mask.double()
        den = w.cumsum(-1).clamp_min(1.0)
        means = (w * x).cumsum(-1) / den
        m2 = ((x - F.pad(means[:, :-1], (1, 0))) * (x - means) * w).cumsum(-1)
        scales = (m2 / (den - 1.0).clamp(min=1.0)).sqrt().clamp(min=c.minimum_scale)
        loc = means.float().reshape(rows, ll, ps)[..., -1].repeat_interleave(ps, dim=-1)
        scale = scales.float().reshape(rows, ll, ps)[..., -1].repeat_interleave(ps, dim=-1)
        scaled = apply_affine_asinh_masked(context, loc, scale, mask, use_asinh=c.use_asinh)
        obs = mask.reshape(rows, ll, ps).any(-1)
        # ONNX has no cummax, and over booleans it equals cumsum > 0.
        key_valid = obs | (obs.long().cumsum(-1) > 0) if c.attend_missing_patches else obs
        preds = self.m._run_two_stream(
            self.m.representation(scaled, mask),
            self.m.representation.forecast_tokens(rows, h),
            build_forecast_time_mask(ll, h, key_valid, context.device),
            None,
            build_forecast_positions(ll, h, obs.float().argmax(-1)),
        )
        aloc, ascale = loc[:, -1:], scale[:, -1:]
        q = denormalize_quantiles(preds, aloc.unsqueeze(-1), ascale.unsqueeze(-1), c.use_asinh)
        return q, aloc[:, 0], ascale[:, 0]


def main(output: str) -> None:
    forecaster = TimestralForecaster.from_pretrained(MODEL, device="cpu", revision=REVISION)
    ps = forecaster.config.patch_size
    rows = torch.export.Dim("rows", min=1, max=4096)
    patches = torch.export.Dim("patches", min=1, max=1024)
    horizon = torch.export.Dim("horizon", min=1, max=forecaster.per_shot_horizon_patches)
    context = torch.randn(3, 12 * ps).cumsum(-1)
    with torch.no_grad():
        torch.onnx.export(
            Block(forecaster),
            (context, torch.ones_like(context, dtype=torch.bool), torch.zeros(4)),
            output,
            input_names=["context", "mask", "horizon"],
            output_names=["quantiles", "loc", "scale"],
            dynamic_shapes={
                "context": {0: rows, 1: ps * patches},
                "mask": {0: rows, 1: ps * patches},
                "horizon": {0: horizon},
            },
            dynamo=True,
            external_data=False,
            opset_version=23,
        )


if __name__ == "__main__":
    main(sys.argv[1])
