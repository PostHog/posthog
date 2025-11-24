# DuckLake copy workflow configuration

The DuckLake copy workflow copies materialized data modeling outputs into a DuckLake-managed S3 bucket. Workers running this workflow must be configured explicitly; otherwise copies will fail before they even reach the first activity.

## Environment variables

The workflow obtains its DuckLake configuration from the following environment variables:

- `DUCKLAKE_CATALOG_DSN`
- `DUCKLAKE_DATA_BUCKET`
- `DUCKLAKE_DATA_ENDPOINT`
- `DUCKLAKE_S3_ACCESS_KEY`
- `DUCKLAKE_S3_SECRET_KEY`

`bin/start` exports sensible defaults for local development, so you usually get a working DuckLake setup just by running the dev script. Temporal workers in staging/production must set these variables directly in their process environment (or via Helm/k8s secrets). If you need to run the workflow against a bespoke DuckLake deployment, override the environment variables before starting the worker—no code changes are required.

## Target bucket layout

Every model copy is written to a deterministic prefix inside the DuckLake data bucket:

```text
s3://<DUCKLAKE_DATA_BUCKET>/data_modeling/team_<team_id>/job_<job_id>/model_<model_label>/<normalized_name>.parquet
```

Re-running a copy simply overwrites the same Parquet object. Choose the bucket so its lifecycle/replication policies fit that structure.

## Required permissions

Temporal workers must be able to:

1. Read from the existing PostHog object storage bucket where Delta tables live (already required for the modeling pipeline).
2. Read/write/delete within the DuckLake data bucket referenced by `DUCKLAKE_DATA_BUCKET`.

For AWS S3, grant the worker role at least `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the DuckLake bucket/prefix (plus `s3:CreateBucket` if you want local MinIO-style auto-creation). For MinIO, reuse the same access/secret keys configured in the `DUCKLAKE_*` variables and ensure they have full access to the DuckLake bucket.
