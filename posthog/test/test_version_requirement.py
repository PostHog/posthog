from unittest.mock import patch

from django.test.testcases import TestCase
from semantic_version.base import SimpleSpec, Version

from posthog.version_requirement import ServiceVersionRequirement


class TestServiceVersionRequirement(TestCase):
    def test_accepted_services(self):
        v1 = ServiceVersionRequirement(service="postgresql", supported_version="==14.0.0")
        v2 = ServiceVersionRequirement(service="clickhouse", supported_version="==21.6.0")
        v3 = ServiceVersionRequirement(service="redis", supported_version="==6.2.6")

        self.assertEqual(v1.service, "postgresql")
        self.assertEqual(v2.service, "clickhouse")
        self.assertEqual(v3.service, "redis")

        self.assertEqual(type(v1.supported_version), SimpleSpec)
        self.assertEqual(type(v2.supported_version), SimpleSpec)
        self.assertEqual(type(v3.supported_version), SimpleSpec)

        self.assertEqual(str(v1.supported_version), "==14.0.0")
        self.assertEqual(str(v2.supported_version), "==21.6.0")
        self.assertEqual(str(v3.supported_version), "==6.2.6")

        try:
            ServiceVersionRequirement(service="kea", supported_version="==2.5.0")
        except Exception as e:
            self.assertEqual(
                str(e),
                "service kea cannot be used to specify a version requirement. service should be one of clickhouse, postgresql, redis",
            )

    def test_service_versions(self):

        version1 = ServiceVersionRequirement.version_string_to_semver("14")
        self.assertEqual(version1.major, 14)
        self.assertEqual(version1.minor, 0)
        self.assertEqual(version1.patch, 0)

        version2 = ServiceVersionRequirement.version_string_to_semver("14.1")
        self.assertEqual(version2.major, 14)
        self.assertEqual(version2.minor, 1)
        self.assertEqual(version2.patch, 0)

        version3 = ServiceVersionRequirement.version_string_to_semver("14.1.2")
        self.assertEqual(version3.major, 14)
        self.assertEqual(version3.minor, 1)
        self.assertEqual(version3.patch, 2)

        version4 = ServiceVersionRequirement.version_string_to_semver("14.1.2.5")
        self.assertEqual(version4.major, 14)
        self.assertEqual(version4.minor, 1)
        self.assertEqual(version4.patch, 2)

        version5 = ServiceVersionRequirement.version_string_to_semver("15.0.0-alpha")
        self.assertEqual(version5.major, 15)
        self.assertEqual(version5.minor, 0)
        self.assertEqual(version5.patch, 0)

        version5 = ServiceVersionRequirement.version_string_to_semver("16.0.0.2-alpha")
        self.assertEqual(version5.major, 16)
        self.assertEqual(version5.minor, 0)
        self.assertEqual(version5.patch, 0)

        version6 = ServiceVersionRequirement.version_string_to_semver("11.13 (Ubuntu 11.13-2.heroku1+1)")
        self.assertEqual(version6.major, 11)
        self.assertEqual(version6.minor, 13)
        self.assertEqual(version6.patch, 0)

    @patch("posthog.version_requirement.ServiceVersionRequirement.get_service_version", lambda x: Version("12.1.2"))
    def test_ranges(self):
        v1 = ServiceVersionRequirement(service="postgresql", supported_version="==14.0.0")
        in_range, service_version = v1.is_service_in_accepted_version()
        self.assertEqual(in_range, False)
        self.assertEqual(str(service_version), "12.1.2")

        v2 = ServiceVersionRequirement(service="postgresql", supported_version="==12.1.2")
        in_range, _ = v2.is_service_in_accepted_version()
        self.assertEqual(in_range, True)

        v3 = ServiceVersionRequirement(service="postgresql", supported_version=">=12.0.0,<12.1.2")
        in_range, _ = v3.is_service_in_accepted_version()
        self.assertEqual(in_range, False)

        v4 = ServiceVersionRequirement(service="postgresql", supported_version=">=12.0.0,<=12.1.2")
        in_range, _ = v4.is_service_in_accepted_version()
        self.assertEqual(in_range, True)

        v5 = ServiceVersionRequirement(service="postgresql", supported_version=">=11.0.0,<=13.0.0")
        in_range, _ = v5.is_service_in_accepted_version()
        self.assertEqual(in_range, True)
