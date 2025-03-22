from rest_framework.exceptions import ValidationError
from snowflake.connector.errors import DatabaseError, ForbiddenError, ProgrammingError

from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models.external_data_schema import get_snowflake_schemas, filter_snowflake_incremental_fields
from posthog.exceptions_capture import capture_exception


class SnowflakeSourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        account_id = self.request_data.get("account_id")
        database = self.request_data.get("database")
        warehouse = self.request_data.get("warehouse")
        role = self.request_data.get("role")
        schema = self.request_data.get("schema")

        auth_type_obj = self.request_data.get("auth_type", {})
        auth_type = auth_type_obj.get("selection", None)
        auth_type_username = auth_type_obj.get("username", None)
        auth_type_password = auth_type_obj.get("password", None)
        auth_type_passphrase = auth_type_obj.get("passphrase", None)
        auth_type_private_key = auth_type_obj.get("private_key", None)

        if not account_id or not warehouse or not database or not schema:
            return False, "Missing required parameters: account id, warehouse, database, schema"

        if auth_type == "password" and (not auth_type_username or not auth_type_password):
            return False, "Missing required parameters: username, password"

        if auth_type == "keypair" and (not auth_type_passphrase or not auth_type_private_key or not auth_type_username):
            return False, "Missing required parameters: passphrase, private key"

        # Store these for schema options
        self.account_id = account_id
        self.database = database
        self.warehouse = warehouse
        self.schema = schema
        self.role = role
        self.auth_type = auth_type
        self.auth_type_username = auth_type_username
        self.auth_type_password = auth_type_password
        self.auth_type_passphrase = auth_type_passphrase
        self.auth_type_private_key = auth_type_private_key

        return True, None

    def get_schema_options(self) -> list[dict]:
        try:
            result = get_snowflake_schemas(
                account_id=self.account_id,
                database=self.database,
                warehouse=self.warehouse,
                user=self.auth_type_username,
                password=self.auth_type_password,
                schema=self.schema,
                role=self.role,
                passphrase=self.auth_type_passphrase,
                private_key=self.auth_type_private_key,
                auth_type=self.auth_type,
            )
            if len(result.keys()) == 0:
                return []

            filtered_results = [
                (table_name, filter_snowflake_incremental_fields(columns)) for table_name, columns in result.items()
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
        except (ProgrammingError, DatabaseError, ForbiddenError) as e:
            exposed_error = self._expose_snowflake_error(e)
            if exposed_error is None:
                capture_exception(e)
            raise ValidationError(exposed_error or self.GENERIC_SNOWFLAKE_ERROR)
        except Exception as e:
            capture_exception(e)
            raise ValidationError(self.GENERIC_SNOWFLAKE_ERROR)

    def _expose_snowflake_error(self, error: ProgrammingError | DatabaseError | ForbiddenError) -> str | None:
        error_msg = error.msg or error.raw_msg or ""

        ERROR_MAPPINGS = {
            "No active warehouse selected in the current session": "No warehouse found for selected role",
            "or attempt to login with another role": "Role specified doesn't exist or is not authorized",
            "Incorrect username or password was specified": "Incorrect username or password was specified",
            "This session does not have a current database": "Database specified not found",
            "Verify the account name is correct": "Can't find an account with the specified account ID",
        }

        for key, value in ERROR_MAPPINGS.items():
            if key in error_msg:
                return value
        return None

    GENERIC_SNOWFLAKE_ERROR = "Could not connect to Snowflake. Please check all connection details are valid."
