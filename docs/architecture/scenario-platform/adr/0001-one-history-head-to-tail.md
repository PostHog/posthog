# One history, journaled at the head and judged at the tail

A scenario run that crosses several teams' services writes one `history.jsonl`. Core journals offers at the head adapter and records truth at the tail through the provider edge. Middle adapters add probes, series and `hops()` diagnostics, never verdicts on units.

Units are joined from outcome to offer by a carrier that the head predicts. For persons and cohorts, that carrier is the deterministic person id. A canary unit checks the prediction before drive.

We chose this over per-adapter invariants because both adapters could pass while a unit lost at the hop between them was counted by neither. We chose it over a shared trace id because that needs production changes, and identity ends where cohort recomputation aggregates.

## Considered options

- **Per-adapter invariants only.** Rejected: a loss between adapters is invisible.
- **A trace id carried through every service.** Rejected: production changes, and it cannot survive aggregation.
- **Resolving the carrier at judge time from the persons database.** Rejected: it puts a product database read inside the core judge.
