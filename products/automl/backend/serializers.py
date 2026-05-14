"""DRF serializers for the AutoML browser.

Everything is read from S3, so these are response shapes — there is no
matching Django model. We use plain `serializers.Serializer` subclasses so
drf-spectacular can still describe the response schema.
"""

from rest_framework import serializers


class TaskSummarySerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Task name (the directory under `tasks/`).")
    has_spec = serializers.BooleanField(help_text="Whether `spec.yaml` exists for this task.")
    spec = serializers.JSONField(allow_null=True, help_text="Parsed `spec.yaml`. Null if missing/unparseable.")
    current_query_version = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Query version pointed at by `queries/HEAD`, e.g. `v2.sql`.",
    )
    current_run_id = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Run id pointed at by the top-level `HEAD` (the currently shipped run).",
    )
    current_run_manifest = serializers.JSONField(
        allow_null=True,
        help_text="Parsed manifest.yaml of the current run, if one exists.",
    )
    run_count = serializers.IntegerField(help_text="Total number of runs stored under this task.")


class RunSummarySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Run id — the directory name under `runs/`.")
    shipped = serializers.BooleanField(help_text="`shipped` flag from the run's `manifest.yaml`.")
    is_current = serializers.BooleanField(help_text="Whether this run is the one pointed at by `HEAD`.")
    manifest = serializers.JSONField(allow_null=True, help_text="Parsed manifest.yaml. Null if missing/unparseable.")


class TaskDetailSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Task name.")
    spec = serializers.JSONField(allow_null=True, help_text="Parsed `spec.yaml`.")
    spec_raw = serializers.CharField(allow_null=True, help_text="Raw `spec.yaml` text — useful for editor previews.")
    queries = serializers.ListField(
        child=serializers.CharField(),
        help_text="Sorted list of query filenames under `queries/` (e.g. `v1.sql`).",
    )
    current_query_version = serializers.CharField(allow_null=True, help_text="Filename pointed at by `queries/HEAD`.")
    runs = RunSummarySerializer(many=True, help_text="All runs under `runs/`, most-recent id first.")
    current_run_id = serializers.CharField(allow_null=True, help_text="Run id pointed at by the top-level `HEAD`.")


class RunDetailSerializer(serializers.Serializer):
    task_name = serializers.CharField(help_text="Owning task name.")
    id = serializers.CharField(help_text="Run id.")
    manifest = serializers.JSONField(allow_null=True, help_text="Parsed manifest.yaml.")
    manifest_raw = serializers.CharField(allow_null=True, help_text="Raw manifest.yaml text.")
    artifacts = serializers.ListField(
        child=serializers.CharField(),
        help_text="Relative paths of every object under the run prefix (excluding `manifest.yaml`).",
    )
    is_current = serializers.BooleanField(help_text="Whether this is the currently shipped run.")


class QueryTextSerializer(serializers.Serializer):
    task_name = serializers.CharField(help_text="Owning task name.")
    version = serializers.CharField(help_text="Query filename, e.g. `v2.sql`.")
    sql = serializers.CharField(help_text="Raw SQL contents.")


class ParquetPreviewSerializer(serializers.Serializer):
    columns = serializers.ListField(child=serializers.CharField(), help_text="Column names in schema order.")
    rows = serializers.ListField(
        child=serializers.DictField(), help_text="The first `returned_rows` rows, as a list of column->value dicts."
    )
    total_rows = serializers.IntegerField(help_text="Total row count in the parquet file.")
    returned_rows = serializers.IntegerField(help_text="Number of rows actually returned (after limit).")
