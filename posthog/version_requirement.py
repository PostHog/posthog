from semantic_version.base import SimpleSpec, Version

from posthog import redis


class ServiceVersionRequirement:
    accepted_services = ("clickhouse", "postgresql", "redis")

    def __init__(self, service, supported_version):
        if service not in self.accepted_services:
            services_str = ", ".join(self.accepted_services)
            raise Exception(
                f"service {service} cannot be used to specify a version requirement. service should be one of {services_str}"
            )

        self.service = service

        try:
            self.supported_version = SimpleSpec(supported_version)
        except:
            raise Exception(
                f"The provided supported_version for service {service} is invalid. See the Docs for SimpleSpec: https://pypi.org/project/semantic-version/"
            )

    def is_service_in_accepted_version(self):
        service_version = self.get_service_version()
        return [service_version in self.supported_version, service_version]

    def get_service_version(self):
        if self.service == "postgresql":
            return self.get_postgres_version()

        if self.service == "clickhouse":
            return self.get_clickhouse_version()

        if self.service == "redis":
            return self.get_redis_version()

    def get_postgres_version(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")

            rows = cursor.fetchone()
            version = rows[0]

        return self.version_string_to_semver(version)

    def get_clickhouse_version(self):
        from ee.clickhouse.client import default_client

        client = default_client()
        rows = client.execute("SELECT version()")
        version = rows[0][0]

        return self.version_string_to_semver(version)

    def get_redis_version(self):
        client = redis.get_client()
        version = client.execute_command("INFO")["redis_version"]
        return self.version_string_to_semver(version)

    @staticmethod
    def version_string_to_semver(version):
        minor = 0
        patch = 0

        # remove e.g. `-alpha`, Postgres metadata (`11.13 (Ubuntu 11.13-2.heroku1+1)`), etc
        version_parts = version.split("(")[0].split("-")[0].split(".")

        major = int(version_parts[0])

        if len(version_parts) > 1:
            minor = int(version_parts[1])

        if len(version_parts) > 2:
            patch = int(version_parts[2])

        return Version(major=major, minor=minor, patch=patch)
