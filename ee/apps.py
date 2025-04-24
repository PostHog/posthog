from django.apps import AppConfig
from braintrust import init_logger
from django.conf import settings


class EnterpriseConfig(AppConfig):
    name = "ee"
    verbose_name = "Enterprise"

    def ready(self):
        init_logger(project_id="a7660c4d-ce6a-480b-b32b-773f0cb92c45", api_key=settings.BRAINTRUST_API_KEY)
