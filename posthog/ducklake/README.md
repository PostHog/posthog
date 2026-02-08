# DuckLake copy workflow configuration

The DuckLake copy workflows copy data into a DuckLake-managed S3 bucket. There are two workflows:

1. **Data Modeling** (`ducklake-copy.data-modeling`) - copies materialized saved query outputs
2. **Data Imports** (`ducklake-copy.data-imports`) - copies external data source imports (Stripe, Hubspot, etc.)

Both workflows share the same infrastructure and configuration. Workers running these workflows must be configured explicitly; otherwise copies will fail before they even reach the first activity.

## Environment variables

The workflow obtains its DuckLake configuration from the following environment variables:

- `DUCKLAKE_RDS_HOST` - Postgres catalog host
- `DUCKLAKE_RDS_PORT` - Postgres catalog port
- `DUCKLAKE_RDS_DATABASE` - Postgres catalog database name
- `DUCKLAKE_RDS_USERNAME` - Postgres catalog username
- `DUCKLAKE_RDS_PASSWORD` - Postgres catalog password
- `DUCKLAKE_BUCKET` - S3 bucket for DuckLake data
- `DUCKLAKE_BUCKET_REGION` - AWS region for the S3 bucket
- `DUCKLAKE_S3_ACCESS_KEY` - S3 access key (optional, for local dev; production uses IRSA)
- `DUCKLAKE_S3_SECRET_KEY` - S3 secret key (optional, for local dev; production uses IRSA)

`bin/start` exports sensible defaults for local development, so you usually get a working DuckLake setup just by running the dev script. Temporal workers in staging/production must set these variables directly in their process environment (or via Helm/k8s secrets). If you need to run the workflow against a bespoke DuckLake deployment, override the environment variables before starting the worker—no code changes are required.

For local dev the defaults are:

- `DUCKLAKE_RDS_HOST=localhost`
- `DUCKLAKE_RDS_PORT=5432`
- `DUCKLAKE_RDS_DATABASE=ducklake_catalog`
- `DUCKLAKE_RDS_USERNAME=posthog`
- `DUCKLAKE_RDS_PASSWORD=posthog`
- `DUCKLAKE_BUCKET=ducklake-dev`
- `DUCKLAKE_BUCKET_REGION=us-east-1`
- `DUCKLAKE_S3_ACCESS_KEY=object_storage_root_user`
- `DUCKLAKE_S3_SECRET_KEY=object_storage_root_password`

## Feature flag gating

Each workflow is gated by its own feature flag (evaluated via `feature_enabled`). Create or update the appropriate flag locally to target the team you are testing with—otherwise the copy workflow will be skipped even if the rest of the configuration is correct.

| Workflow      | Feature Flag                           |
| ------------- | -------------------------------------- |
| Data Modeling | `ducklake-data-modeling-copy-workflow` |
| Data Imports  | `ducklake-data-imports-copy-workflow`  |

## Target bucket layout

Every copy is written to a deterministic schema inside DuckLake. Each workflow namespaces its data under a workflow-specific schema:

### Data Modeling

- **Schema**: `data_modeling_team_<team_id>`
- **Table**: `<model_label>` (derived from saved query name)
- **Example**: `ducklake.data_modeling_team_123.my_saved_query`

### Data Imports

- **Schema**: `data_imports_team_<team_id>`
- **Table**: `<source_type>_<normalized_name>_<schema_id_hex[:8]>`
- **Example**: `ducklake.data_imports_team_123.stripe_invoices_a1b2c3d4`

Re-running a copy simply overwrites the same table. Choose the bucket so its lifecycle/replication policies fit that structure.

## Required permissions

Temporal workers must be able to:

1. Read from the existing PostHog object storage bucket where Delta tables live (already required for the modeling pipeline).
2. Read/write/delete within the DuckLake data bucket referenced by `DUCKLAKE_BUCKET`.

For AWS S3, grant the worker role at least `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the DuckLake bucket/prefix (plus `s3:CreateBucket` if you want local MinIO-style auto-creation). For MinIO, reuse the same access/secret keys configured in the `DUCKLAKE_*` variables and ensure they have full access to the DuckLake bucket.

## Local testing (dev)

Follow these checklists to exercise the DuckLake copy workflows on a local checkout.

### Testing Data Modeling workflow

1. **Start the dev stack**
   Run `hogli start` (or `bin/start`) so Postgres, MinIO, Temporal, and all DuckLake defaults are up. Make sure the `ducklake-data-modeling-copy-workflow` feature flag is enabled for the team you plan to use.

2. **Trigger a model materialization from the app**
   In the PostHog UI, open Data Warehouse → Views, pick (or create) a view, open the Materialization section, enable it if needed, and click **Sync now**. This schedules the `data-modeling-run` workflow for that team/view.

3. **Observe the data-modeling workflow**
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm a `data-modeling-run` execution appears. Wait for it to finish successfully.

4. **Verify the DuckLake copy workflow runs**
   Once the modeling workflow completes it automatically starts `ducklake-copy.data-modeling` as a child run. You should see it listed in the same Temporal UI; wait for the run to complete.

5. **Query the new DuckLake table**
   The copy activity creates a table at `ducklake.data_modeling_team_<team_id>.<model_label>`. From any DuckDB shell you can inspect it, for example:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_endpoint='localhost:19000';
     SET s3_use_ssl=false;
     SET s3_access_key_id='object_storage_root_user';
     SET s3_secret_access_key='object_storage_root_password';
     SET s3_url_style='path';

     ATTACH 'ducklake:postgres:dbname=ducklake_catalog host=localhost user=posthog password=posthog'
       AS ducklake (DATA_PATH 's3://ducklake-dev/');

     -- Discover available schemas
     SELECT * FROM information_schema.schemata WHERE catalog_name = 'ducklake';

     -- List tables in the ducklake catalog
     SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = 'ducklake';

     -- Query a specific table
     SELECT * FROM ducklake.data_modeling_team_${TEAM_ID}.${MODEL_LABEL} LIMIT 10;
   "
   ```

### Testing Data Imports workflow

1. **Start the dev stack**
   Run `hogli start` (or `bin/start`) so Postgres, MinIO, Temporal, and all DuckLake defaults are up. Make sure the `ducklake-data-imports-copy-workflow` feature flag is enabled for the team you plan to use.

2. **Trigger a data import sync from the app**
   In the PostHog UI, open Data Warehouse → Sources, connect a source (e.g., Stripe, Hubspot), select the schemas to sync, and click **Sync**. This schedules the `external-data-job` workflow.

3. **Observe the external-data-job workflow**
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm an `external-data-job` execution appears. Wait for it to finish successfully.

4. **Verify the DuckLake copy workflow runs**
   Once the import workflow completes it automatically starts `ducklake-copy.data-imports` as a child run. You should see it listed in the same Temporal UI; wait for the run to complete.

5. **Query the new DuckLake table**
   The copy activity creates a table at `ducklake.data_imports_team_<team_id>.<source_type>_<table_name>_<schema_id_hex>`. From any DuckDB shell you can inspect it:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_endpoint='localhost:19000';
     SET s3_use_ssl=false;
     SET s3_access_key_id='object_storage_root_user';
     SET s3_secret_access_key='object_storage_root_password';
     SET s3_url_style='path';

     ATTACH 'ducklake:postgres:dbname=ducklake_catalog host=localhost user=posthog password=posthog'
       AS ducklake (DATA_PATH 's3://ducklake-dev/');

     -- Discover available schemas
     SELECT * FROM information_schema.schemata WHERE catalog_name = 'ducklake';

     -- List tables in the ducklake catalog
     SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = 'ducklake';

     -- Query a specific table
     SELECT * FROM ducklake.data_imports_team_${TEAM_ID}.${SOURCE_TYPE}_${TABLE_NAME}_${SCHEMA_ID_HEX} LIMIT 10;
   "
   ```
