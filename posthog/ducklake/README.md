# DuckLake copy workflow configuration

The DuckLake copy and registration workflows write data into a DuckLake-managed S3 bucket. There are three workflows:

1. **Data Modeling** (`ducklake-copy.data-modeling`) - copies materialized saved query outputs
2. **Data Imports** (`ducklake-copy.data-imports`) - copies external data source imports (Stripe, Hubspot, etc.)
3. **Data Import Registration** (`ducklake-register.data-imports`) - copies and registers prepared Parquet files from completed imports

The workflows share the same infrastructure and configuration. Workers running these workflows must be configured explicitly; otherwise copies will fail before they even reach the first activity.

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
- `DUCKLAKE_RDS_DATABASE=ducklake`
- `DUCKLAKE_RDS_USERNAME=posthog`
- `DUCKLAKE_RDS_PASSWORD=posthog`
- `DUCKLAKE_BUCKET=ducklake-dev`
- `DUCKLAKE_BUCKET_REGION=us-east-1`
- `DUCKLAKE_S3_ACCESS_KEY=object_storage_root_user`
- `DUCKLAKE_S3_SECRET_KEY=object_storage_root_password`
- `DUCKGRES_HOST=localhost`
- `DUCKGRES_PORT=15432`
- `DUCKGRES_DATABASE=ducklake`
- `DUCKGRES_USERNAME=posthog`
- `DUCKGRES_PASSWORD=posthog`

## Feature flag gating

Each workflow is gated by its own feature flag (evaluated via `feature_enabled`). Create or update the appropriate flag locally to target the team you are testing with—otherwise the copy workflow will be skipped even if the rest of the configuration is correct.

| Workflow                 | Feature Flag                                  |
| ------------------------ | --------------------------------------------- |
| Data Modeling            | `ducklake-data-modeling-copy-workflow`        |
| Data Imports             | `ducklake-data-imports-copy-workflow`         |
| Data Import Registration | `ducklake-data-imports-registration-workflow` |

The two data-import flags are independent and target the same stable DuckLake table. During rollout, enable only the intended path for a project; if both run for the same import, the last atomic table swap wins.

## Target bucket layout

Every copy is written to a deterministic schema inside DuckLake. Each workflow namespaces its data under a workflow-specific schema:

### Data Modeling

- **Schema**: `posthog_data_modeling_team_<team_id>`
- **Table**: `<model_label>` (derived from saved query name)
- **Example**: `ducklake.posthog_data_modeling_team_123.my_saved_query`

### Data Imports and Data Import Registration

- **Schema**: `posthog_data_imports_team_<team_id>`
- **Table**: `<source_type>_<prefix>_<normalized_name>` (prefix is user-defined on the external data source)
- **Example**: `ducklake.posthog_data_imports_team_123.stripe_prod_invoices`
- **Registered files**: `s3://<ducklake-bucket>/<ducklake-schema>/<ducklake-table>/_imports/<source-schema-id>/<job-id>/<prepared-relative-path>`

Each completed import creates a timestamped prepared Parquet snapshot in the data warehouse bucket. The registration workflow copies those objects directly into the DuckLake bucket, preserving Hive partition directories, registers the destination objects with `ducklake_add_data_files`, verifies the shadow table's row count, and only then swaps it into the stable table name through the Duckgres PostgreSQL connection. Registration, verification, and the swap share one catalog transaction, so a mismatch leaves the previous table live. Each import job gets its own object prefix and child workflow ID, so a later sync does not append into the previous snapshot.

The registered objects are permanent DuckLake data files, not staging files. Old generations remain reachable through DuckLake snapshots until snapshot expiration and old-file cleanup make them eligible for object deletion. Choose the bucket lifecycle policy with that retention behavior in mind.

## Required permissions

Temporal workers must be able to:

1. Read from the existing PostHog object storage bucket where Delta tables live (already required for the modeling pipeline).
2. Read/write/delete within the DuckLake data bucket referenced by `DUCKLAKE_BUCKET`.

For AWS S3, grant the worker role at least `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the DuckLake bucket/prefix (plus `s3:CreateBucket` for local auto-creation). Local development uses the configured SeaweedFS object store and the `DUCKLAKE_*` access keys.

## Local testing (dev)

Follow these checklists to exercise the DuckLake copy workflows on a local checkout.

### Testing Data Modeling workflow

1. **Start the dev stack**
   Run `hogli start` (or `bin/start`) so Postgres, SeaweedFS, Temporal, and all DuckLake defaults are up. Make sure the `ducklake-data-modeling-copy-workflow` feature flag is enabled for the team you plan to use.

2. **Trigger a model materialization from the app**
   In the PostHog UI, open Data Warehouse → Views, pick (or create) a view, open the Materialization section, enable it if needed, and click **Sync now**. This schedules the `data-modeling-run` workflow for that team/view.

3. **Observe the data-modeling workflow**
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm a `data-modeling-run` execution appears. Wait for it to finish successfully.

4. **Verify the DuckLake copy workflow runs**
   Once the modeling workflow completes it automatically starts `ducklake-copy.data-modeling` as a child run. You should see it listed in the same Temporal UI; wait for the run to complete.

5. **Query the new DuckLake table**
   The copy activity creates a table at `ducklake.posthog_data_modeling_team_<team_id>.<model_label>`. From any DuckDB shell you can inspect it, for example:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_endpoint='localhost:19000';
     SET s3_use_ssl=false;
     SET s3_access_key_id='object_storage_root_user';
     SET s3_secret_access_key='object_storage_root_password';
     SET s3_url_style='path';

     ATTACH 'ducklake:postgres:dbname=ducklake host=localhost user=posthog password=posthog'
       AS ducklake (DATA_PATH 's3://ducklake-dev/');

     -- Discover available schemas
     SELECT * FROM information_schema.schemata WHERE catalog_name = 'ducklake';

     -- List tables in the ducklake catalog
     SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = 'ducklake';

     -- Query a specific table
     SELECT * FROM ducklake.posthog_data_modeling_team_${TEAM_ID}.${MODEL_LABEL} LIMIT 10;
   "
   ```

### Testing Data Imports workflows

1. **Start the dev stack**
   Run `hogli start` (or `bin/start`) so Postgres, Duckgres, SeaweedFS, Temporal, and all DuckLake defaults are up. Enable either `ducklake-data-imports-copy-workflow` for the existing Delta-copy path or `ducklake-data-imports-registration-workflow` for the prepared-Parquet path.

2. **Trigger a data import sync from the app**
   In the PostHog UI, open Data Warehouse → Sources, connect a source (e.g., Stripe, Hubspot), select the schemas to sync, and click **Sync**. This schedules the `external-data-job` workflow.

3. **Observe the external-data-job workflow**
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm an `external-data-job` execution appears. Wait for it to finish successfully.

4. **Verify the selected DuckLake workflow runs**
   Once the import workflow completes it starts both independently gated child workflows. The enabled path appears as either `ducklake-copy.data-imports` or `ducklake-register.data-imports`; the disabled path exits after its gate activity.

5. **Query the new DuckLake table**
   The copy activity creates a table at `ducklake.posthog_data_imports_team_<team_id>.<source_type>_<prefix>_<table_name>`. From any DuckDB shell you can inspect it:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_endpoint='localhost:19000';
     SET s3_use_ssl=false;
     SET s3_access_key_id='object_storage_root_user';
     SET s3_secret_access_key='object_storage_root_password';
     SET s3_url_style='path';

     ATTACH 'ducklake:postgres:dbname=ducklake host=localhost user=posthog password=posthog'
       AS ducklake (DATA_PATH 's3://ducklake-dev/');

     -- Discover available schemas
     SELECT * FROM information_schema.schemata WHERE catalog_name = 'ducklake';

     -- List tables in the ducklake catalog
     SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = 'ducklake';

     -- Query a specific table
     SELECT * FROM ducklake.posthog_data_imports_team_${TEAM_ID}.${SOURCE_TYPE}_${PREFIX}_${TABLE_NAME} LIMIT 10;
   "
   ```
