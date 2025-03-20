from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource
from .auth import get_hubspot_access_token_from_code


class HubspotSourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        code = self.request_data.get("code", "")
        redirect_uri = self.request_data.get("redirect_uri", "")

        if not code or not redirect_uri:
            return False, "Missing required parameters: code, redirect_uri"

        try:
            # Just validate credentials by attempting to get access token
            get_hubspot_access_token_from_code(code, redirect_uri=redirect_uri)
            return True, None
        except Exception as e:
            return False, f"Invalid credentials: Hubspot authentication failed - {str(e)}"

    def get_schema_options(self) -> list[dict]:
        return self._get_explicit_schema_options(ExternalDataSource.Type.HUBSPOT)
