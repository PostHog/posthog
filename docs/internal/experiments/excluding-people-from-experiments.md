# Excluding people from an experiment

`exposure_criteria.exclusions` removes people from an experiment entirely: their exposures and their
metric events, including everything recorded before the filter started matching.
It exists for consent withdrawal, but it applies to any "this person shouldn't be in the results"
case.

It accepts person and cohort filters only, and it applies whether or not the experiment configures a
custom exposure event.

## Why not `exposure_config.properties`

`exposure_config.properties` filters the exposure _events_.
Two things follow, and both were sharp edges people hit before exclusions existed:

- It is only reachable when the experiment is on custom exposure criteria.
  An experiment left on Default had no exclusion surface at all.
- Under person-on-events, a person property read from an event is the value snapshotted when that
  event was ingested.
  Setting `consent_withdrawn` on someone today does not change events recorded yesterday, so their
  earlier exposures stay in the results.
  A cohort filter behaved differently, because cohort membership compiles to a query-time
  `person_id IN cohort` check.

That asymmetry is exactly the failure mode exclusions close: it looked filtered and wasn't.

## How it compiles

`build_exposure_exclusion_expr` (in `products/experiments/backend/hogql_queries/exposure_query_logic.py`)
produces a `NOT` over the union of the exclusions, keyed on the person rather than the event row:

- Cohort filters become `person_id IN COHORT <id>`, resolved at query time.
- Person filters become `person_id IN (SELECT id FROM persons WHERE …)`, so they read current person
  state rather than the event-time snapshot.

Keying on the person is what avoids a half-counted person: filtering rows would drop only the events
that match, leaving someone exposed in the denominator but unable to convert, which reads as a
result against whichever variant they landed in.

Unsupported filter types raise `UnsupportedExposureExclusionError` rather than being dropped.
A silently ignored exclusion is worse than a failed query: the results look filtered.

## Interaction with precomputed exposures

An experiment with exclusions does not read the precomputed exposures table.
Those rows are built once and cached for weeks, which would pin exclusion membership to build time
and defeat the point.
Expect direct-scan latency on experiments that use this.

## Server-side flag evaluation

The common shape for a backend-evaluated experiment:

1. Your backend records the withdrawal and marks the person, by setting a person property or by
   adding them to a static cohort.
   Note that the SDK instance the user opted out of will not send anything, so the marker has to come
   from a path that is still allowed to capture.
2. Add `consent_withdrawn is true` (or the cohort) as an exposure exclusion on the experiment.
3. Results recalculate with that person's whole history removed.

For local evaluation, resolve the properties you filter on into `personProperties` at the call site,
otherwise the flag can't be evaluated locally and falls back to a network call.
