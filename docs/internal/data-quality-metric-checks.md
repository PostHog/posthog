# Catalog metric reads for data quality

Data quality consumers can read saved metric summaries and HogQL definitions through the data
catalog facade. Reads are team-scoped and exclude deleted metrics. Batched name lookups retrieve
only the requested IDs and names; summaries keep SQL text and parameter values separate.

HogQL definition reads treat absent or null parameter maps as empty. Authoring validation applies
saved parameters as placeholders, matching metric execution. A bare field named after a parameter
is not a parameter reference.

These contracts support the upcoming metric check API. Check authoring and execution are added
in the next backend layer.
