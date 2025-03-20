import re

from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource
from . import validate_credentials


class ChargebeeSourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        api_key = self.request_data.get("api_key", "")
        site_name = self.request_data.get("site_name", "")

        # Chargebee uses the term 'site' but it is effectively the subdomain
        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if not subdomain_regex.match(site_name):
            return False, "Invalid credentials: Chargebee site name is incorrect"

        if not validate_credentials(api_key=api_key, site_name=site_name):
            return False, "Invalid credentials: Chargebee credentials are incorrect"

        return True, None

    def get_schema_options(self) -> list[dict]:
        return self._get_default_schema_options(ExternalDataSource.Type.CHARGEBEE)
