from django.apps import AppConfig


class EnterpriseConfig(AppConfig):
    name = "ee"
    verbose_name = "Enterprise"

    def ready(self) -> None:
        # Connect the Vercel experimentation-item sync receivers at app-population. They used to
        # wire in via a viewset import; the lazy API router no longer pulls that, so connect here.
        # The receivers live in a light module so ready() does not import ee.vercel.integration.
        from ee.vercel import receivers  # noqa: F401, PLC0415
