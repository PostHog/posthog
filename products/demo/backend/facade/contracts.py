"""Public data contracts for the demo product.

The demo facade is behavioral: it exposes the matrix-simulation entry points (the
`MatrixManager`, the `HedgeboxMatrix`/`SpikeGPTMatrix` scenarios) and data-generation
helpers, which write into core models and return primitives. The product owns no data
model of its own, so there are no product-owned contracts to define here — the file
exists to mark the product as isolated and is the home for any future cross-boundary
data record.
"""
