# DuckLake copy workflow configuration

The DuckLake copy workflow copies materialized data modeling outputs into a DuckLake-managed S3 bucket. Workers running this workflow must be configured explicitly; otherwise copies will fail before they even reach the first activity.

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

## Feature flag gating

The modeling workflow launches the DuckLake copy child only when the
`ducklake-data-modeling-copy-workflow` feature flag is enabled for the team (as evaluated
via `feature_enabled`). Create or update that flag locally to target the team you are testing
with—otherwise the copy workflow will be skipped even if the rest of the configuration is correct.

## Target bucket layout

Every model copy is written to a deterministic prefix inside the DuckLake data bucket. Each workflow
namespaces its data under a workflow identifier (e.g., `data_modeling` for the Temporal pipeline captured
in this doc):

```text
s3://<DUCKLAKE_BUCKET>/<workflow_identifier>/team_<team_id>/job_<job_id>/model_<model_label>/<normalized_name>.parquet
```

For the Temporal data modeling copy workflow, `<workflow_identifier>` is `data_modeling`.

Re-running a copy simply overwrites the same Parquet object. Choose the bucket so its lifecycle/replication policies fit that structure.

## Required permissions

Temporal workers must be able to:

1. Read from the existing PostHog object storage bucket where Delta tables live (already required for the modeling pipeline).
2. Read/write/delete within the DuckLake data bucket referenced by `DUCKLAKE_BUCKET`.

For AWS S3, grant the worker role at least `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the DuckLake bucket/prefix (plus `s3:CreateBucket` if you want local MinIO-style auto-creation). For MinIO, reuse the same access/secret keys configured in the `DUCKLAKE_*` variables and ensure they have full access to the DuckLake bucket.

## Local testing (dev)

Follow this checklist to exercise the DuckLake copy workflow on a local checkout without needing extra tribal knowledge:

1. **Start the dev stack**  
   Run `hogli start` (or `bin/start`) so Postgres, MinIO, Temporal, and all DuckLake defaults are up. Make sure the `ducklake-data-modeling-copy-workflow` feature flag is enabled for the team you plan to use.

2. **Trigger a model materialization from the app**  
   In the PostHog UI, open Data Warehouse → Views, pick (or create) a view, open the Materialization section, enable it if needed, and click **Sync now**. This schedules the `data-modeling-run` workflow for that team/view.

3. **Observe the data-modeling workflow**  
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm a `data-modeling-run` execution appears. Wait for it to finish successfully.

4. **Verify the DuckLake copy workflow runs**  
   Once the modeling workflow completes it automatically starts `ducklake-copy.data-modeling` as a child run. You should see it listed in the same Temporal UI; wait for the run to complete.

5. **Query the new DuckLake table**  
   The copy activity registers a view named `ducklake_dev.data_modeling_team_<team_id>.model_<model_label>`. From any DuckDB shell you can inspect it, for example:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_region='us-east-1';

     ATTACH 'postgres:dbname=ducklake host=localhost port=5432 user=posthog password=posthog'
       AS ducklake (TYPE ducklake, DATA_PATH 's3://ducklake-dev/');
     SELECT * FROM ducklake.data_modeling_team_${TEAM_ID}.model_${MODEL_LABEL} LIMIT 10;
   "
   ```

   Replace `${TEAM_ID}` and `${MODEL_LABEL}` with the team/model that was materialized (the model label is logged by the workflow and matches the saved query’s UUID hex).
