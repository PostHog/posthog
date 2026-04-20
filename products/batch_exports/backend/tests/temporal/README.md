# Testing batch exports

This module contains unit tests covering activities, workflows, and helper functions that power batch exports. Tests are divided by destination, and some destinations require setup steps to enable tests.

## Testing BigQuery batch exports

BigQuery batch exports can be tested against a real BigQuery instance, but doing so requires additional setup. BigQuery currently supports multiple authentication mechanisms:

1. Authenticating directly with a JSON key file
2. Using an integration populated with a JSON key file
3. Using an integration without any keys to impersonate the account using our own credentials

All tests still require a JSON key file for setup so, regardless of which authentication method is being tested, all these tests are skipped unless an environment variable pointing to a BigQuery credentials file (`GOOGLE_APPLICATION_CREDENTIALS=/path/to/my/project-credentials.json`) is set.

Additionally, any tests that are specific to the 3rd authentication method in the list (impersonation) require AWS credentials to be available to `boto3`, and the following settings to be configured:

- `BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT`
- `BATCH_EXPORT_BIGQUERY_STS_AUDIENCE_FIELD`

For PostHog employees, development values for these settings are available in the PostHog password manager.

> [!WARNING]
> Since BigQuery batch export tests require additional setup, we skip them by default and will not be ran by automated CI pipelines. Please ensure these tests pass when making changes that affect BigQuery batch exports.

When starting from scratch, to enable testing for BigQuery batch exports, we require:

1. A BigQuery project
2. A Google Cloud service account with BigQuery access in said project. See the [BigQuery batch export documentation](https://posthog.com/docs/cdp/batch-exports/bigquery#setting-up-bigquery-access) on detailed steps to setup a service account.
3. A [JSON key file](https://cloud.google.com/iam/docs/keys-create-delete#creating) for the service account, saved to a local file.
4. If testing impersonation:
   - Another Google Cloud service account that can be used to impersonate the service account from the previous step is required.
   - A workload identity federation provider and pool setup to grant access to this other service account.

For PostHog employees, all of this is already setup for you. You can obtain a JSON key file, and the necessary values for the settings detailed above from the PostHog password manager.

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

S3 batch exports are tested against a MinIO bucket available in the local development stack. However there are also unit tests that specifically target an S3 bucket (like `test_s3_export_workflow_with_s3_bucket`) and a Google Cloud Storage (GCS) bucket.

If no environment variables are defined, then just the tests targeting MinIO will be run (the tests targeting S3/GCS will be skipped).

### Using an S3 bucket

Additional setup is required to run the tests against an S3 bucket:

1. Ensure you are logged in to an AWS account.
2. Create or choose an existing S3 bucket from that AWS account to use as the test bucket.
3. Create or choose an existing KMS key id from that AWS account to use in tests.
4. Make sure the role/user you are logged in as has permissions to use the bucket and KMS key.

> [!NOTE]
> For PostHog employees, your password manager contains a set of credentials for S3 batch exports development testing. You may populate your development environment with these credentials and use the provided test bucket and KMS key.

With these setup steps done, we can run the S3-specific tests from the root of the `posthog` repo with:

```bash
DEBUG=1 S3_TEST_KMS_KEY_ID='1111111-2222-3333-4444-55555555555' S3_TEST_BUCKET='your-test-bucket' AWS_ACCESS_KEY_ID="AAAA" AWS_SECRET_ACCESS_KEY="BBBB" pytest products/batch_exports/backend/tests/temporal/destinations/s3/test_workflow_with_s3_bucket.py
```

Replace the environment variables with the values obtained from the setup steps.

### Using a GCS bucket

Additional setup is required to run the tests against a GCS bucket:

1. Ensure you are logged in to a Google Cloud account.
2. Create or choose an existing GCS bucket from that account to use as the test bucket.
3. Create or choose an existing service principal or user.
4. Make sure this service principal or user has permissions to use the bucket.
5. Generate HMAC keys (AWS compatible access keys). This can be done by going to `Cloud Storage -> Settings -> Interoperability`

> [!NOTE]
> For PostHog employees, your password manager contains a set of credentials for GCS batch exports development testing. You may populate your development environment with these credentials and use the provided test bucket.

With these setup steps done, we can run the GCS-specific tests from the root of the `posthog` repo with:

```bash
DEBUG=1 GCS_TEST_BUCKET='your-test-bucket' AWS_ACCESS_KEY_ID="AAAA" AWS_SECRET_ACCESS_KEY="BBBB" pytest products/batch_exports/backend/tests/temporal/destinations/s3/test_workflow_with_gcs_bucket.py
```

Replace the environment variables with the values obtained from the setup steps.

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

## Testing Azure Blob Storage batch exports

Azure Blob Storage batch exports are tested against the [Azurite](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azurite) emulator available in the local development stack. This allows running tests without requiring real Azure credentials.

### Using the Azurite emulator (default)

The Azurite emulator provides Azure Storage API compatibility locally. To run the tests:

1. Ensure the development Docker stack is running (includes Azurite):

   ```bash
   docker compose -f docker-compose.dev.yml --profile batch-exports up -d
   ```

2. Run the tests from the root of the `posthog` repo:

   ```bash
   DEBUG=1 pytest products/batch_exports/backend/tests/temporal/destinations/azure_blob/ -v
   ```

### Using a real Azure Storage account

To run tests against a real Azure Storage account (for E2E validation):

1. Create an Azure Storage account
2. Create a container for testing
3. Generate a connection string with access to the container

> [!NOTE]
> For PostHog employees, check the password manager for Azure Storage development credentials.

With these setup steps done, we can run the Azure-specific tests from the root of the `posthog` repo with:

```bash
DEBUG=1 AZURE_STORAGE_CONNECTION_STRING='DefaultEndpointsProtocol=https;AccountName=<ACCOUNT_NAME>;AccountKey=<ACCOUNT_KEY>;EndpointSuffix=core.windows.net' \
    AZURE_TEST_CONTAINER='<CONTAINER_NAME>' \
    pytest products/batch_exports/backend/tests/temporal/destinations/azure_blob/test_workflow_with_azure_account.py -v
```
