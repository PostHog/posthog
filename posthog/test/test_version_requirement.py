from unittest.mock import patch

from django.test.testcases import TestCase

from semantic_version.base import SimpleSpec, Version

from posthog import version_requirement
from posthog.version_requirement import ServiceVersionRequirement


class TestServiceVersionRequirement(TestCase):
    def test_accepted_services(self):
        v1 = ServiceVersionRequirement(service="postgresql", supported_version="==14.0.0")
        v2 = ServiceVersionRequirement(service="clickhouse", supported_version="==22.3.0")
        v3 = ServiceVersionRequirement(service="redis", supported_version="==6.2.6")

        assert v1.service == "postgresql"
        assert v2.service == "clickhouse"
        assert v3.service == "redis"

        assert type(v1.supported_version) == SimpleSpec
        assert type(v2.supported_version) == SimpleSpec
        assert type(v3.supported_version) == SimpleSpec

        assert str(v1.supported_version) == "==14.0.0"
        assert str(v2.supported_version) == "==22.3.0"
        assert str(v3.supported_version) == "==6.2.6"

        try:
            ServiceVersionRequirement(service="kea", supported_version="==2.5.0")
        except Exception as e:
            assert str(e) == "service kea cannot be used to specify a version requirement. service should be one of clickhouse, postgresql, redis"

    def test_service_versions(self):
        version1 = version_requirement.version_string_to_semver("14")
        assert version1.major == 14
        assert version1.minor == 0
        assert version1.patch == 0

        version2 = version_requirement.version_string_to_semver("14.1")
        assert version2.major == 14
        assert version2.minor == 1
        assert version2.patch == 0

        version3 = version_requirement.version_string_to_semver("14.1.2")
        assert version3.major == 14
        assert version3.minor == 1
        assert version3.patch == 2

        version4 = version_requirement.version_string_to_semver("14.1.2.5")
        assert version4.major == 14
        assert version4.minor == 1
        assert version4.patch == 2

        version5 = version_requirement.version_string_to_semver("15.0.0-alpha")
        assert version5.major == 15
        assert version5.minor == 0
        assert version5.patch == 0

        version5 = version_requirement.version_string_to_semver("16.0.0.2-alpha")
        assert version5.major == 16
        assert version5.minor == 0
        assert version5.patch == 0

        version6 = version_requirement.version_string_to_semver("11.13 (Ubuntu 11.13-2.heroku1+1)")
        assert version6.major == 11
        assert version6.minor == 13
        assert version6.patch == 0

    @patch(
        "posthog.version_requirement.ServiceVersionRequirement.get_service_version",
        lambda x: Version("12.1.2"),
    )
    def test_ranges(self):
        v1 = ServiceVersionRequirement(service="postgresql", supported_version="==14.0.0")
        in_range, service_version = v1.is_service_in_accepted_version()
        assert not in_range
        assert str(service_version) == "12.1.2"

        v2 = ServiceVersionRequirement(service="postgresql", supported_version="==12.1.2")
        in_range, _ = v2.is_service_in_accepted_version()
        assert in_range

        v3 = ServiceVersionRequirement(service="postgresql", supported_version=">=12.0.0,<12.1.2")
        in_range, _ = v3.is_service_in_accepted_version()
        assert not in_range

        v4 = ServiceVersionRequirement(service="postgresql", supported_version=">=12.0.0,<=12.1.2")
        in_range, _ = v4.is_service_in_accepted_version()
        assert in_range

        v5 = ServiceVersionRequirement(service="postgresql", supported_version=">=11.0.0,<=13.0.0")
        in_range, _ = v5.is_service_in_accepted_version()
        assert in_range
