# Scorecard v2 adds fields and renames nothing

Scorecard v2 adds `adapters`, `owners`, `versions` and `head_dirty`. Every v1 property keeps its name, including the Workflows-owned ones. Only a new adapter's own invariants and measurements are prefixed `<adapter>__`, with `-` mapped to `_`.

`runner_version` hashes only what shapes a run's outcome, through an explicit include list in core. A test fails on any directory that is neither included nor listed as not-outcome.

Stored scorecard events, insights and baseline bands outlive the code. Renaming every key would break all of them with no reader gaining anything. An exclusion list lets the next read-only module, such as a viewer or a store, silently re-baseline every card. Dots in property names need quoting in HogQL and read as nesting in pickers, so the separator is `__`.

v2 lands with the directory moves, as one re-baseline.
