from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from . import filter_incremental_fields, get_schemas, validate_credentials


class BigQuerySourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        dataset_id = self.request_data.get("dataset_id", "")
        key_file = self.request_data.get("key_file", {})
        if not validate_credentials(dataset_id=dataset_id, key_file=key_file):
            return False, "Invalid credentials: BigQuery credentials are incorrect"
        return True, None

    def get_schema_options(self) -> list[dict]:
        dataset_id = self.request_data.get("dataset_id", "")
        key_file = self.request_data.get("key_file", {})
        project_id = key_file.get("project_id")
        private_key = key_file.get("private_key")
        private_key_id = key_file.get("private_key_id")
        client_email = key_file.get("client_email")
        token_uri = key_file.get("token_uri")

        bq_schemas = get_schemas(
            dataset_id=dataset_id,
            project_id=project_id,
            private_key=private_key,
            private_key_id=private_key_id,
            client_email=client_email,
            token_uri=token_uri,
        )

        filtered_results = [
            (table_name, filter_incremental_fields(columns)) for table_name, columns in bq_schemas.items()
        ]

        return [
            {
                "table": table_name,
                "should_sync": False,
                "incremental_fields": [
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in columns
                ],
                "incremental_available": True,
                "incremental_field": columns[0][0] if len(columns) > 0 and len(columns[0]) > 0 else None,
                "sync_type": None,
            }
            for table_name, columns in filtered_results
        ]
