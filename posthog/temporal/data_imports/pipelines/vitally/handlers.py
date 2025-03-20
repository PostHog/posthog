import re

from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource
from . import validate_credentials


class VitallySourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        secret_token = self.request_data.get("secret_token", "")
        region = self.request_data.get("region", "")
        subdomain = self.request_data.get("subdomain", "")

        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if region == "US" and not subdomain_regex.match(subdomain):
            return False, "Invalid credentials: Vitally subdomain is incorrect"

        if not validate_credentials(subdomain=subdomain, secret_token=secret_token, region=region):
            return False, "Invalid credentials: Vitally credentials are incorrect"

        return True, None

    def get_schema_options(self) -> list[dict]:
        return self._get_explicit_schema_options(ExternalDataSource.Type.VITALLY)
