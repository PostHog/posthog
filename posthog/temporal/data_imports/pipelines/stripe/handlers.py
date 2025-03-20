from posthog.temporal.data_imports.pipelines.source.handlers import SourceHandler
from posthog.warehouse.models import ExternalDataSource
from . import validate_credentials


class StripeSourceHandler(SourceHandler):
    def validate_credentials(self) -> tuple[bool, str | None]:
        key = self.request_data.get("stripe_secret_key", "")
        if not validate_credentials(api_key=key):
            return False, "Invalid credentials: Stripe secret is incorrect"
        return True, None

    def get_schema_options(self) -> list[dict]:
        return self._get_explicit_schema_options(ExternalDataSource.Type.STRIPE)
