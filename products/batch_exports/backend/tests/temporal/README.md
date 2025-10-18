# Testing batch exports

This module contains unit tests covering activities, workflows, and helper functions that power batch exports. Tests are divided by destination, and some destinations require setup steps to enable tests.

## Testing BigQuery batch exports

BigQuery batch exports can be tested against a real BigQuery instance, but doing so requires additional setup. For this reason, these tests are skipped unless an environment variable pointing to a BigQuery credentials file (`GOOGLE_APPLICATION_CREDENTIALS=/path/to/my/project-credentials.json`) is set.

> [!WARNING]
> Since BigQuery batch export tests require additional setup, we skip them by default and will not be ran by automated CI pipelines. Please ensure these tests pass when making changes that affect BigQuery batch exports.

To enable testing for BigQuery batch exports, we require:

1. A BigQuery project and dataset
2. A BigQuery ServiceAccount with access to said project and dataset. See the [BigQuery batch export documentation](https://posthog.com/docs/cdp/batch-exports/bigquery#setting-up-bigquery-access) on detailed steps to setup a ServiceAccount.

Then, a [key](https://cloud.google.com/iam/docs/keys-create-delete#creating) can be created for the BigQuery ServiceAccount and saved to a local file. For PostHog employees, this file should already be available under the PostHog password manager.

Tests for BigQuery batch exports can be then run from the root of the `posthog` repo:

```bash
DEBUG=1 GOOGLE_APPLICATION_CREDENTIALS=/path/to/my/project-credentials.json pytest products/batch_exports/backend/tests/temporal/destinations/test_bigquery_batch_export_workflow.py
```

## Testing Redshift batch exports

Redshift batch exports can be tested against a real Redshift (or Redshift Serverless) instance, with additional setup steps required. Moreover, testing the 'COPY' version of the Redshift batch export additionally requires access to an S3 bucket in the same region as the Redshift instance.

Due to these additional requirements, all or some of these tests are skipped unless Redshift credentials and S3 credentials are specified in the environment.

> [!WARNING]
> Since Redshift batch export tests require additional setup, we skip them by default and will not be ran by automated CI pipelines. Please ensure these tests pass when making changes that affect Redshift batch exports.

To enable testing for Redshift batch exports, we require:

1. A Redshift (or Redshift Serverless) instance.
2. Network access to this instance (via a VPN connection or jumphost, making a Redshift instance publicly available has serious security implications).
3. User credentials (user requires `CREATEDB` permissions for testing but **not** superuser access).
4. (Optional: For 'COPY' tests): An S3 bucket and credentials to access it.

For PostHog employees, check the password manager as a set of development credentials should already be available. You will also need to use the `dev` exit node in Tailscale and be added to the `group:engineering` group in the tailnet policy. With these credentials, and Tailscale setup, we can run the tests from the root of the `posthog` repo with:

```bash
DEBUG=1 REDSHIFT_HOST=workgroup.111222333.region.redshift-serverless.amazonaws.com REDSHIFT_USER=test_user REDSHIFT_PASSWORD=test_password pytest products/batch_exports/backend/tests/temporal/destinations/redshift
```

Replace the `REDSHIFT_*` environment variables with the values obtained from the setup steps.

To additionally also run 'COPY' tests (available in the `test_copy_activity.py` module), make sure AWS credentials are available in the environment (or pass them along), and set the `S3_TEST_BUCKET` environment variable to the name of the test bucket:

```bash
DEBUG=1 AWS_ACCESS_KEY_ID="AAAA" AWS_SECRET_ACCESS_KEY="BBBB" AWS_REGION="region" S3_TEST_BUCKET="my-test-bucket" REDSHIFT_HOST=workgroup.111222333.region.redshift-serverless.amazonaws.com REDSHIFT_USER=test_user REDSHIFT_PASSWORD=test_password pytest products/batch_exports/backend/tests/temporal/destinations/redshift
```

## Testing S3 batch exports

S3 batch exports are tested against a MinIO bucket available in the local development stack. However there are also unit tests that specifically target an S3 bucket (like `test_s3_export_workflow_with_s3_bucket`). Additional setup is required to run those specific tests:

1. Ensure you are logged in to an AWS account.
2. Create or choose an existing S3 bucket from that AWS account to use as the test bucket.
3. Create or choose an existing KMS key id from that AWS account to use in tests.
4. Make sure the role/user you are logged in as has permissions to use the bucket and KMS key.

> [!NOTE]
> For PostHog employees, your password manager contains a set of credentials for S3 batch exports development testing. You may populate your development environment with these credentials and use the provided test bucket and KMS key.

With these setup steps done, we can run all tests (MinIO and S3 bucket) from the root of the `posthog` repo with:

```bash
DEBUG=1 S3_TEST_KMS_KEY_ID='1111111-2222-3333-4444-55555555555' S3_TEST_BUCKET='your-test-bucket' pytest products/batch_exports/backend/tests/temporal/destinations/test_s3_batch_export_workflow.py
```

Replace the `S3_*` environment variables with the values obtained from the setup steps.

## Testing Snowflake batch exports

Snowflake batch exports are tested against a real Snowflake instance, with additional setup steps required. Due to this requirement, these tests are skipped unless Snowflake credentials are specified in the environment.

> [!WARNING]
> Since Snowflake batch export tests require additional setup, we skip them by default and will not be ran by automated CI pipelines. Please ensure these tests pass when making changes that affect Snowflake batch exports.

To enable testing for Snowflake batch exports, we require:

1. A Snowflake account.
2. A Snowflake user and role with the necessary permissions to create and manage tables in the database.
3. A Snowflake warehouse (compute resource) that the user has access to.

For PostHog employees, check the password manager as a set of development credentials should already be available. You can either use these or ask someone to create a new user for you.

We currently support 2 types of authentication for Snowflake batch exports:

### Password authentication

For password authentication, you can run the tests from the root of the `posthog` repo with:

```bash
DEBUG=1 SNOWFLAKE_WAREHOUSE='your-warehouse' SNOWFLAKE_USERNAME='your-username' SNOWFLAKE_PASSWORD='your-password' SNOWFLAKE_ACCOUNT='your-account' SNOWFLAKE_ROLE='your-role' pytest products/batch_exports/backend/tests/temporal/destinations/test_snowflake_batch_export_workflow.py
```

Replace the `SNOWFLAKE_*` environment variables with the values obtained from the setup steps.

### Key pair authentication

For key pair authentication, you will first need to generate a key pair. You can find instructions on how to do this in the [Snowflake documentation](https://docs.snowflake.com/en/user-guide/key-pair-auth#configuring-key-pair-authentication)

Once you have generated the key pair, you can run the tests from the root of the `posthog` repo with:

```bash
DEBUG=1 SNOWFLAKE_WAREHOUSE='your-warehouse' SNOWFLAKE_USERNAME='your-username' SNOWFLAKE_PRIVATE_KEY='your-private-key' SNOWFLAKE_PRIVATE_KEY_PASSPHRASE='your-passphrase' SNOWFLAKE_ACCOUNT='your-account' SNOWFLAKE_ROLE='your-role' pytest products/batch_exports/backend/tests/temporal/destinations/test_snowflake_batch_export_workflow.py
```

Replace the `SNOWFLAKE_*` environment variables with the values obtained from the setup steps.
