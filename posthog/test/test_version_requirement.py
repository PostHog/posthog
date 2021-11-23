from unittest.mock import patch

from django.test.testcases import TestCase
from semantic_version.base import SimpleSpec, Version

from posthog.version_requirement import VersionRequirement


class TestVersionRequirement(TestCase):
    def test_accepted_services(self):
        v1 = VersionRequirement(service="postgres", version_range="==14.0.0")
        v2 = VersionRequirement(service="clickhouse", version_range="==21.6.0")

        self.assertEqual(v1.service, "postgres")
        self.assertEqual(v2.service, "clickhouse")

        self.assertEqual(type(v1.version_range), SimpleSpec)
        self.assertEqual(type(v2.version_range), SimpleSpec)

        self.assertEqual(str(v1.version_range), "==14.0.0")
        self.assertEqual(str(v2.version_range), "==21.6.0")

        try:
            VersionRequirement(service="kea", version_range="==2.5.0")
        except Exception as e:
            self.assertEqual(
                str(e),
                "service kea cannot be used to specify a version requirement. service should be one of clickhouse, postgres",
            )

    def test_service_versions(self):

        version1 = VersionRequirement.version_string_to_semver("14")
        self.assertEqual(version1.major, 14)
        self.assertEqual(version1.minor, 0)
        self.assertEqual(version1.patch, 0)

        version2 = VersionRequirement.version_string_to_semver("14.1")
        self.assertEqual(version2.major, 14)
        self.assertEqual(version2.minor, 1)
        self.assertEqual(version2.patch, 0)

        version3 = VersionRequirement.version_string_to_semver("14.1.2")
        self.assertEqual(version3.major, 14)
        self.assertEqual(version3.minor, 1)
        self.assertEqual(version3.patch, 2)

        version4 = VersionRequirement.version_string_to_semver("14.1.2.5")
        self.assertEqual(version4.major, 14)
        self.assertEqual(version4.minor, 1)
        self.assertEqual(version4.patch, 2)

        version5 = VersionRequirement.version_string_to_semver("15.0.0-alpha")
        self.assertEqual(version5.major, 15)
        self.assertEqual(version5.minor, 0)
        self.assertEqual(version5.patch, 0)

        version5 = VersionRequirement.version_string_to_semver("16.0.0.2-alpha")
        self.assertEqual(version5.major, 16)
        self.assertEqual(version5.minor, 0)
        self.assertEqual(version5.patch, 0)

    @patch("posthog.version_requirement.VersionRequirement.get_service_version", lambda x: Version("12.1.2"))
    def test_ranges(self):
        v1 = VersionRequirement(service="postgres", version_range="==14.0.0")
        in_range, service_version = v1.is_service_in_accepted_version()
        self.assertEqual(in_range, False)
        self.assertEqual(str(service_version), "12.1.2")

        v2 = VersionRequirement(service="postgres", version_range="==12.1.2")
        in_range, _ = v2.is_service_in_accepted_version()
        self.assertEqual(in_range, True)

        v3 = VersionRequirement(service="postgres", version_range=">=12.0.0,<12.1.2")
        in_range, _ = v3.is_service_in_accepted_version()
        self.assertEqual(in_range, False)

        v4 = VersionRequirement(service="postgres", version_range=">=12.0.0,<=12.1.2")
        in_range, _ = v4.is_service_in_accepted_version()
        self.assertEqual(in_range, True)

        v5 = VersionRequirement(service="postgres", version_range=">=11.0.0,<=13.0.0")
        in_range, _ = v5.is_service_in_accepted_version()
        self.assertEqual(in_range, True)
