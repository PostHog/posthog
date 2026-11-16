# Core and adapters live in `nodejs/tests/scenarios/`

The platform stays at `nodejs/tests/scenarios/{core,adapters/<name>}`, with an import rule: core imports no adapter, and no adapter imports another. We extract the Workflows runner into `core/` plus `adapters/workflows/` first, and build persons and cohorts as the second adapter before the contract is frozen.

A separate repository would split the adapter from the service code it boots and lose the shared lockfile. `common/` or `tools/` would make it look like product-neutral infrastructure before a second team owns any of it. Moving to `tools/scenarios/` stays a later option, once a team other than Workflows owns an adapter.
