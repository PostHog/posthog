from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource


class SalesforceSourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        salesforce_integration_id = self.request_data.get("salesforce_integration_id", "")
        if not salesforce_integration_id:
            return False, "Missing required parameters: Salesforce integration ID"

        return True, None

    def get_schema_options(self) -> list[dict]:
        return self._get_explicit_schema_options(ExternalDataSource.Type.SALESFORCE)
