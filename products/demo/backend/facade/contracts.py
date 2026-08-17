"""Public data contracts for the demo product.

The demo facade is behavioral: it exposes the matrix-simulation entry points (the
`MatrixManager`, the `HedgeboxMatrix`/`SpikeGPTMatrix` scenarios) and data-generation
helpers, which write into core models and return primitives. The product owns no data
model of its own, so there are no product-owned contracts to define here, and this file
is only the home for any future cross-boundary data record.

Demo is not isolated: its facade hands out those behavioral classes (`MatrixManager`,
`Matrix`, `HedgeboxMatrix`, `SpikeGPTMatrix`) directly rather than as frozen contracts,
driven across the boundary by `posthog/api/signup.py` and the demo management commands.
"""
