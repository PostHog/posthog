"""Public data contracts for the demo product.

The demo facade is behavioral: it exposes the matrix-simulation entry points (the
`MatrixManager`, the `HedgeboxMatrix`/`SpikeGPTMatrix` scenarios) and data-generation
helpers, which write into core models and return primitives. The product owns no data
model of its own, so there are no product-owned contracts to define here — this file is
the home for any future cross-boundary data record.

Because those entry points are classes rather than contract data, callers reach every
method on them, and the methods live in ``logic/`` rather than here. turbo.json therefore
keeps each defining module in the contract-check inputs, so a change to one still re-runs
the Django suite — core drives `MatrixManager.ensure_account_and_save` from
`posthog/api/signup.py`, and that call is invisible to tach (the import of ``facade.api``
is legal; the class travels out through it). Adding a class to this facade means adding
its module there too, or `hogli product:lint` will fail.
"""
