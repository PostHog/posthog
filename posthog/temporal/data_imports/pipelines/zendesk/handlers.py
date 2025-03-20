import re

from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource
from . import validate_credentials


class ZendeskSourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        subdomain = self.request_data.get("subdomain", "")
        api_key = self.request_data.get("api_key", "")
        email_address = self.request_data.get("email_address", "")

        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if not subdomain_regex.match(subdomain):
            return False, "Invalid credentials: Zendesk subdomain is incorrect"

        if not validate_credentials(subdomain=subdomain, api_key=api_key, email_address=email_address):
            return False, "Invalid credentials: Zendesk credentials are incorrect"

        return True, None

    def get_schema_options(self) -> list[dict]:
        return self._get_explicit_schema_options(ExternalDataSource.Type.ZENDESK)
