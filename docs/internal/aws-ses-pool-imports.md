# Amazon SES pool imports

The `dedicated_ip_pools` table lists pool names and adds details from `GetDedicatedIpPool`.
AWS reserves `ses-shared-pool` and `ses-default-dedicated-pool` for its shared and default dedicated pools.
See the [AWS pool documentation](https://docs.aws.amazon.com/ses/latest/dg/managing-ip-pools.html).

If AWS lists either reserved pool but rejects its detail request with `BadRequestException`, the connector keeps a row with `pool_name` only.
Missing details do not imply a scaling mode or ownership of dedicated IP addresses.
If AWS returns details for either pool, the connector keeps them.

Import and schema discovery use the same detail-fetch helper.
The endpoint configuration limits the fallback to exact names, and no other endpoint enables it.
The helper reuses the existing signed requests and tracked HTTP transport.
Pagination, retry handling, and row normalization remain unchanged.

A rejected list request, a rejected custom pool detail request, or a different detail error does not use this fallback.
Existing handling for deleted items, access failures, and transient errors remains unchanged.

## Tests

Run the connector tests:

```sh
hogli test products/warehouse_sources/backend/temporal/data_imports/sources/aws_ses/tests/test_aws_ses.py
```

Run the import workflow regression test with the local development services:

```sh
hogli test products/warehouse_sources/backend/temporal/data_imports/tests/e2e/test_aws_ses_source.py
```

The workflow test supplies controlled AWS HTTP responses and checks the imported warehouse data.
It does not test a live AWS account.
