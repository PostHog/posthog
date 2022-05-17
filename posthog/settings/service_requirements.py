from posthog.settings.base_variables import DEBUG, IS_COLLECT_STATIC, TEST
from posthog.settings.utils import get_from_env, print_warning, str_to_bool
from posthog.version_requirement import ServiceVersionRequirement

SKIP_SERVICE_VERSION_REQUIREMENTS = get_from_env(
    "SKIP_SERVICE_VERSION_REQUIREMENTS", TEST or IS_COLLECT_STATIC or DEBUG, type_cast=str_to_bool
)

if SKIP_SERVICE_VERSION_REQUIREMENTS and not (TEST or DEBUG):
    print_warning(["Skipping service version requirements. This is dangerous and PostHog might not work as expected!"])

SERVICE_VERSION_REQUIREMENTS = [
    ServiceVersionRequirement(service="postgresql", supported_version=">=11.0.0,<=14.1.0",),
    ServiceVersionRequirement(service="redis", supported_version=">=5.0.0,<=6.3.0",),
    ServiceVersionRequirement(service="clickhouse", supported_version=">=21.6.0,<22.4.0"),
]
