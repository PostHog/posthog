# Testing batch exports

This module contains unit tests covering activities, workflows, and helper functions that power batch exports. Tests are divided by destination, and some destinations require setup steps to enable tests.

## Testing BigQuery batch exports

BigQuery batch exports can be tested against a real BigQuery instance, but doing so requires additional setup. For this reason, these tests are skipped unless an environment variable pointing to a BigQuery credentials file (`GOOGLE_APPLICATION_CREDENTIALS=/path/to/my/project-credentials.json`) is set.

> :warning: Since BigQuery batch export tests require additional setup, we skip them by default and will not be ran by automated CI pipelines. Please ensure these tests pass when making changes that affect BigQuery batch exports.

To enable testing for BigQuery batch exports, we require:
1. A BigQuery project and dataset
2. A BigQuery ServiceAccount with access to said project and dataset. See the [BigQuery batch export documentation](https://posthog.com/docs/cdp/batch-exports/bigquery#setting-up-bigquery-access) on detailed steps to setup a ServiceAccount.

Then, a [key](https://cloud.google.com/iam/docs/keys-create-delete#creating) can be created for the BigQuery ServiceAccount and saved to a local file. For PostHog employees, this file should already be available under the PostHog password manager.

Tests for BigQuery batch exports can be then run from the root of the `posthog` repo:

```bash
DEBUG=1 GOOGLE_APPLICATION_CREDENTIALS=/path/to/my/project-credentials.json pytest posthog/temporal/tests/batch_exports/test_bigquery_batch_export_workflow.py
```

## Testing Redshift batch exports

Redshift batch exports can be tested against a real Redshift (or Redshift Serverless) instance, with additional setup steps required. Due to this requirement, these tests are skipped unless Redshift credentials are specified in the environment.

> :warning: Since Redshift batch export tests require additional setup, we skip them by default and will not be ran by automated CI pipelines. Please ensure these tests pass when making changes that affect Redshift batch exports.

To enable testing for Redshift batch exports, we require:
1. A Redshift (or Redshift Serverless) instance.
2. Network access to this instance (via a VPN connection or jumphost, making a Redshift instance publicly available has serious security implications).
3. User credentials (user requires `CREATEDB` permissions for testing but **not** superuser access).

For PostHog employees, check the password manager as a set of development credentials should already be available. With these credentials, and after connecting to the appropriate VPN, we can run the tests from the root of the `posthog` repo with:

```bash
DEBUG=1 REDSHIFT_HOST=workgroup.111222333.region.redshift-serverless.amazonaws.com REDSHIFT_USER=test_user REDSHIFT_PASSWORD=test_password pytest posthog/temporal/tests/batch_exports/test_redshift_batch_export_workflow.py
```

Replace the `REDSHIFT_*` environment variables with the values obtained from the setup steps.

## Testing S3 batch exports

S3 batch exports are tested against a MinIO bucket available in the local development stack. However there are also unit tests that specifically target an S3 bucket. Additional setup is required to run those specific tests:

1. Ensure you are logged in to an AWS account.
2. Create or choose an existing S3 bucket from that AWS account to use as the test bucket.
3. Create or choose an existing KMS key id from that AWS account to use in tests.
4. Make sure the role/user you are logged in as has permissions to use the bucket and KMS key.

For PostHog employees, check your password manager for these details.

With these setup steps done, we can run all tests (MinIO and S3 bucket) from the root of the `posthog` repo with:

```bash
DEBUG=1 S3_TEST_KMS_KEY_ID='1111111-2222-3333-4444-55555555555' S3_TEST_BUCKET='your-test-bucket' pytest posthog/temporal/tests/batch_exports/test_s3_batch_export_workflow.py
```

Replace the `S3_*` environment variables with the values obtained from the setup steps.
