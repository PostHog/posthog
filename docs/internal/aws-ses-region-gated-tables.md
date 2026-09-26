# Amazon SES region-gated tables

Amazon SES is regional, and some SESv2 operations exist in only a subset of regions.
`multi_region_endpoints` is one: it calls `ListMultiRegionEndpoints`, which lists global endpoints.
A region either offers that feature or does not.

A region that does not offer an operation answers HTTP 400 with `BadRequestException`.
SESv2 declares `BadRequestException` with zero members, so the response carries no message.
The list operations also declare no `NotFoundException`, so there is no other code to read.

## Why the wording stays hedged

The same code and the same empty body come back when AWS faults the request itself, and nothing separates the two cases.

The response holds no discriminator, as above.
The request holds none either.
`PageSize` is the shape `MaxItems`, declared as `{"type": "integer"}` with no `min` and no `max`, on every operation this source calls except `ListMultiRegionEndpoints`, which uses `PageSizeV2` (`min: 1`, `max: 1000`).
So AWS can reject the page size the connector chose, and a bodyless 400 on a `PageSize`-only request does not prove the region lacks the table.
`GetAccount` takes no input at all and still declares `BadRequestException`, which shows AWS does not limit the code to input faults.

The error therefore names the region and leaves the cause open: it says Amazon SES rejected the request and gave no reason, that the table might not be available in that region, and what to check next.
Wording that states the region as the proven cause would misreport every 400 with another cause, on the sync error, the schema-picker reason, and credential validation alike.

A definite message needs a reliable discriminator from AWS first, such as a distinct error code or a populated message.

## Where the message appears

Schema discovery probes each table with `PageSize=1`.
A table the region cannot serve is reported in the schema picker with this message, so it is not selectable.
A table already selected fails its sync with the same message, and the source classifies the failure as non-retryable.

## Tests

Run the connector tests:

```sh
hogli test products/warehouse_sources/backend/temporal/data_imports/sources/aws_ses/tests/test_aws_ses.py
```
