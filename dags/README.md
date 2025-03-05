# Dagster

## Running locally

You'll need to set DAGSTER_HOME

Easiest is to just start jobs from your cli
```bash
dagster job execute -m dags.export_query_logs_to_s3 --config dags/query_log_example.yaml
```

You can also run the interface
```bash
dagster dev
```

By default this will run on http://127.0.0.1:3000/
