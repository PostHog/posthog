from django.apps import AppConfig

from ee.settings import VERSION_REQUIREMENTS_EE


class EnterpriseConfig(AppConfig):
    name = "ee"
    verbose_name = "Enterprise"

    def ready():
        for version_requirement in VERSION_REQUIREMENTS_EE:
            [in_range, version] = version_requirement.is_service_in_accepted_version()
            if not in_range:
                start_anyway = input(
                    f"Service {version_requirement.service} is in version {version}. Expected range: {str(version_requirement.version_range)}. PostHog may not work correctly with the current version. Continue? [y/n]"
                )
                if start_anyway.lower() != "y":
                    print(f"Unsupported version for service {version_requirement.service}, exiting...")
                    exit(1)
