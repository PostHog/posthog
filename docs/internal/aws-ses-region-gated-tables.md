# Amazon SES region-gated tables

Amazon SES is regional, and some SESv2 operations exist in only a subset of regions.
`multi_region_endpoints` is one: it calls `ListMultiRegionEndpoints`, which lists global endpoints.
A region either offers that feature or does not.

A region that does not offer an operation answers HTTP 400 with `BadRequestException`.
SESv2 declares `BadRequestException` with zero members, so the response carries no message.
The list operations also declare no `NotFoundException`, so there is no other code to read.

The connector separates that case from a 400 the account caused.
A request marked `fixed_inputs_only` carries nothing the account chose: no name in the path, no saved page token, and no date filter.
Its only input is `PageSize`, which SESv2 range-checks against its own model.
A bodyless 400 on such a request can only mean the region does not serve the operation, so the error names the region and tells the operator what to do.
Every other bodyless 400 keeps the earlier, hedged wording, because a path name, a page token, or a date filter is an input AWS can legitimately reject.

Schema discovery probes each table with `PageSize=1`, which is a `fixed_inputs_only` request.
A table the region cannot serve is reported in the schema picker with the same message, so it is not selectable.
A table already selected fails its sync with that message, and the source classifies the failure as non-retryable.

## Tests

Run the connector tests:

```sh
hogli test products/warehouse_sources/backend/temporal/data_imports/sources/aws_ses/tests/test_aws_ses.py
```
