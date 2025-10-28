import re
import time
import uuid
import inspect
import datetime as dt
import resource
import threading
from collections.abc import Callable, Generator, Iterator
from contextlib import ExitStack, contextmanager
from functools import wraps
from typing import Any, Optional, Union

import pytest
import unittest
import freezegun
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

# we have to import pendulum for the side effect of importing it
# freezegun.FakeDateTime and pendulum don't play nicely otherwise
import pendulum  # noqa F401
import sqlparse
from rest_framework.test import APITestCase as DRFTestCase
from syrupy.extensions.amber import AmberSnapshotExtension

from posthog.hogql import (
    ast,
    query as hogql_query_module,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.visitor import clone_expr

from posthog import rate_limit, redis
from posthog.clickhouse.adhoc_events_deletion import (
    ADHOC_EVENTS_DELETION_TABLE_SQL,
    DROP_ADHOC_EVENTS_DELETION_TABLE_SQL,
)
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.clickhouse.custom_metrics import (
    CREATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE,
    CREATE_CUSTOM_METRICS_COUNTERS_VIEW,
    CUSTOM_METRICS_EVENTS_RECENT_LAG_VIEW,
    CUSTOM_METRICS_REPLICATION_QUEUE_VIEW,
    CUSTOM_METRICS_TEST_VIEW,
    CUSTOM_METRICS_VIEW,
    TRUNCATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE,
)
from posthog.clickhouse.materialized_columns import MaterializedColumn
from posthog.clickhouse.plugin_log_entries import TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_MV,
    QUERY_LOG_ARCHIVE_NEW_MV_SQL,
    QUERY_LOG_ARCHIVE_NEW_TABLE_SQL,
)
from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.helpers.two_factor_session import email_mfa_token_generator
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Dashboard, DashboardTile, Insight, Organization, Team, User
from posthog.models.behavioral_cohorts.sql import (
    BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL,
    BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL,
    BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL,
    DROP_BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL,
    DROP_BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL,
    DROP_BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL,
)
from posthog.models.channel_type.sql import (
    CHANNEL_DEFINITION_DATA_SQL,
    CHANNEL_DEFINITION_DICTIONARY_SQL,
    CHANNEL_DEFINITION_TABLE_SQL,
    DROP_CHANNEL_DEFINITION_DICTIONARY_SQL,
    DROP_CHANNEL_DEFINITION_TABLE_SQL,
)
from posthog.models.cohort.sql import TRUNCATE_COHORTPEOPLE_TABLE_SQL
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_TABLE_SQL,
    DROP_DISTRIBUTED_EVENTS_TABLE_SQL,
    DROP_EVENTS_TABLE_SQL,
    EVENTS_TABLE_SQL,
    TRUNCATE_EVENTS_RECENT_TABLE_SQL,
)
from posthog.models.event.util import bulk_create_events
from posthog.models.exchange_rate.sql import (
    DROP_EXCHANGE_RATE_DICTIONARY_SQL,
    DROP_EXCHANGE_RATE_TABLE_SQL,
    EXCHANGE_RATE_DATA_BACKFILL_SQL,
    EXCHANGE_RATE_DICTIONARY_SQL,
    EXCHANGE_RATE_TABLE_SQL,
)
from posthog.models.group.sql import TRUNCATE_GROUPS_TABLE_SQL
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.models.person import Person
from posthog.models.person.sql import (
    DROP_PERSON_TABLE_SQL,
    PERSONS_TABLE_SQL,
    TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
    TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
    TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
    TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL,
)
from posthog.models.person.util import bulk_create_persons, create_person
from posthog.models.project import Project
from posthog.models.property_definition import DROP_PROPERTY_DEFINITIONS_TABLE_SQL, PROPERTY_DEFINITIONS_TABLE_SQL
from posthog.models.raw_sessions.sessions_v2 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL,
    DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL,
    DROP_RAW_SESSION_SHARDED_TABLE_SQL,
    DROP_RAW_SESSION_VIEW_SQL,
    DROP_RAW_SESSION_WRITABLE_TABLE_SQL,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL,
    RAW_SESSIONS_TABLE_MV_SQL,
    RAW_SESSIONS_TABLE_SQL,
    WRITABLE_RAW_SESSIONS_TABLE_SQL,
)
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3,
    DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3,
    DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3,
    DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3,
    DROP_RAW_SESSION_VIEW_SQL_V3,
    DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3,
    RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3,
    RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3,
    RAW_SESSIONS_TABLE_MV_SQL_V3,
    SHARDED_RAW_SESSIONS_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_TABLE_SQL_V3,
)
from posthog.models.sessions.sql import (
    DISTRIBUTED_SESSIONS_TABLE_SQL,
    DROP_SESSION_MATERIALIZED_VIEW_SQL,
    DROP_SESSION_TABLE_SQL,
    DROP_SESSION_VIEW_SQL,
    SESSIONS_TABLE_MV_SQL,
    SESSIONS_TABLE_SQL,
    SESSIONS_VIEW_SQL,
)
from posthog.models.web_preaggregated.sql import (
    DROP_WEB_BOUNCES_DAILY_SQL,
    DROP_WEB_BOUNCES_HOURLY_SQL,
    DROP_WEB_BOUNCES_SQL,
    DROP_WEB_BOUNCES_STAGING_SQL,
    DROP_WEB_STATS_DAILY_SQL,
    DROP_WEB_STATS_HOURLY_SQL,
    DROP_WEB_STATS_SQL,
    DROP_WEB_STATS_STAGING_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
    WEB_BOUNCES_SQL,
    WEB_STATS_COMBINED_VIEW_SQL,
    WEB_STATS_DAILY_SQL,
    WEB_STATS_HOURLY_SQL,
    WEB_STATS_SQL,
)
from posthog.models.web_preaggregated.team_selection import (
    DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL,
    DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL,
    WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL,
)
from posthog.session_recordings.sql.session_recording_event_sql import (
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
    DROP_SESSION_RECORDING_EVENTS_TABLE_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.test.assert_faster_than import assert_faster_than

# Make sure freezegun ignores our utils class that times functions
freezegun.configure(extend_ignore_list=["posthog.test.assert_faster_than"])


persons_cache_tests: list[dict[str, Any]] = []
events_cache_tests: list[dict[str, Any]] = []
persons_ordering_int: int = 0


# Expand string diffs
unittest.util._MAX_LENGTH = 2000  # type: ignore


def clean_varying_query_parts(query, replace_all_numbers):
    # :TRICKY: team_id changes every test, avoid it messing with snapshots.
    if replace_all_numbers:
        query = re.sub(r"(\"?) = \d+", r"\1 = 99999", query)
        query = re.sub(r"(\"?) (in|IN) \(\d+(, ?\d+)*\)", r"\1 \2 (1, 2, 3, 4, 5 /* ... */)", query)
        query = re.sub(r"(\"?) (in|IN) \[\d+(, ?\d+)*\]", r"\1 \2 [1, 2, 3, 4, 5 /* ... */]", query)
        # replace "uuid" IN ('00000000-0000-4000-8000-000000000001'::uuid) effectively:
        query = re.sub(
            r"\"uuid\" (in|IN) \('[0-9a-f-]{36}'(::uuid)?(, '[0-9a-f-]{36}'(::uuid)?)*\)",
            r""""uuid" \1 ('00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000001'::uuid /* ... */)\n""",
            query,
        )
        query = re.sub(r"'[0-9a-f]{32}'::uuid", r"'00000000000000000000000000000000'::uuid", query)
        query = re.sub(r"'[0-9a-f-]{36}'::uuid", r"'00000000-0000-0000-0000-000000000000'::uuid", query)
        query = re.sub(
            r"'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'",
            r"'00000000-0000-0000-0000-000000000000'",
            query,
        )
        query = re.sub(
            r".\"ref\" = '([0-9a-f]{32}|[0-9a-f-]{36}|[0-9]+|[A-Za-z0-9\_\-]+)'", """."ref" = '0001'""", query
        )
    else:
        query = re.sub(r"(team|project|cohort)_id(\"?) = \d+", r"\1_id\2 = 99999", query)
        query = re.sub(
            r"(team|project|cohort)_id(\"?) (in|IN) \(\d+(, ?\d+)*\)", r"\1_id\2 \3 (1, 2, 3, 4, 5 /* ... */)", query
        )
        query = re.sub(
            r"(team|project|cohort)_id(\"?) (in|IN) \[\d+(, ?\d+)*\]", r"\1_id\2 \3 [1, 2, 3, 4, 5 /* ... */]", query
        )
        query = re.sub(r"\d+ (as|AS) (team|project|cohort)_id(\"?)", r"99999 \1 \2_id\3", query)

    # feature flag conditions use primary keys as columns in queries, so replace those always
    query = re.sub(r"flag_\d+_condition", r"flag_X_condition", query)
    query = re.sub(r"flag_\d+_super_condition", r"flag_X_super_condition", query)

    # replace django cursors
    query = re.sub(r"_django_curs_[0-9sync_]*\"", r'_django_curs_X"', query)

    # hog ql checks some ids differently
    query = re.sub(
        r"equals\(([^.]+\.)?((team|project|cohort)_id)?, \d+\)",
        r"equals(\1\2, 99999)",
        query,
    )

    # replace survey uuids
    # replace arrays like "survey_id in ['017e12ef-9c00-0000-59bf-43ddb0bddea6', '017e12ef-9c00-0001-6df6-2cf1f217757f']"
    query = re.sub(
        r"survey_id in \['[0-9a-f-]{36}'(, '[0-9a-f-]{36}')*\]",
        r"survey_id in ['00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0000-000000000001' /* ... */]",
        query,
    )

    # replace arrays like "survey_id in ['017e12ef-9c00-0000-59bf-43ddb0bddea6', '017e12ef-9c00-0001-6df6-2cf1f217757f']"
    query = re.sub(
        r"\"posthog_survey_actions\"\.\"survey_id\" IN \('[^']+'::uuid(, '[^']+'::uuid)*\)",
        r"'posthog_survey_actions'.'survey_id' IN ('00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000001'::uuid, /* ... */])",
        query,
    )

    # replace session uuids
    # replace arrays like "in(s.session_id, ['ea376ce0-d365-4c75-8015-0407e71a1a28'])"
    query = re.sub(
        r"in\((?:s\.)?session_id, \['[0-9a-f-]{36}'(, '[0-9a-f-]{36}')*\]\)",
        r"in(s.session_id, ['00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0000-000000000001' /* ... */]",
        query,
    )

    #### Cohort replacements
    # replace cohort id lists in queries too
    query = re.sub(
        r"in\(([^,]*cohort_id),\s*\[(\d+(?:,\s*\d+)*)]\)",
        r"in(\1, [1, 2, 3, 4, 5 /* ... */])",
        query,
    )
    # replace explicit timestamps in cohort queries
    query = re.sub(
        r"timestamp > '20\d\d-\d\d-\d\d \d\d:\d\d:\d\d'", r"timestamp > 'explicit_redacted_timestamp'", query
    )
    # and where the HogQL doesn't match the above

    # Often we use a now from python to upper bound event times.
    # Replace all dates that could be today in any timezone with "today"
    today = dt.datetime.now(dt.UTC)
    yesterday = today - dt.timedelta(days=1)
    tomorrow = today + dt.timedelta(days=1)
    days_to_sub = "|".join([x.strftime("%Y-%m-%d") for x in [yesterday, today, tomorrow]])
    query = re.sub(
        rf"toDateTime64\('({days_to_sub}) \d\d:\d\d:\d\d.\d+', 6, '(.+?)'\)",
        r"toDateTime64('today', 6, '\2')",
        query,
    )

    # KLUDGE we tend not to replace dates in tests so trying to avoid replacing every date here
    # replace all dates where the date is
    if "equals(argMax(person_distinct_id_overrides.is_deleted" in query or "INSERT INTO cohortpeople" in query:
        # those tests have multiple varying dates like toDateTime64('2025-01-08 00:00:00.000000', 6, 'UTC')
        query = re.sub(
            r"toDateTime64\('20\d\d-\d\d-\d\d \d\d:\d\d:\d\d.\d+', 6, '(.+?)'\)",
            r"toDateTime64('explicit_redacted_timestamp', 6, '\1')",
            query,
        )

    # replace cohort generated conditions
    query = re.sub(
        r"_condition_\d+_level",
        r"_condition_X_level",
        query,
    )

    # replace cohort tuples
    # like (tuple(cohortpeople.cohort_id, cohortpeople.version), [(35, 0)])
    query = re.sub(
        r"\(tuple\((.*)\.cohort_id, (.*)\.version\), \[(\(\d+, \d+\)(?:, \(\d+, \d+\))*)\]\)",
        r"(tuple(\1.cohort_id, \2.version), [(99999, 0)])",
        query,
    )
    #### Cohort replacements end

    # Replace organization_id and notebook_id lookups, for postgres
    query = re.sub(
        rf"""("organization_id"|"posthog_organization"\."id"|"posthog_notebook"."id") = '[^']+'::uuid""",
        r"""\1 = '00000000-0000-0000-0000-000000000000'::uuid""",
        query,
    )
    query = re.sub(
        rf"""("organization_id"|"posthog_organization"\."id"|"posthog_notebook"."id") IN \('[^']+'::uuid\)""",
        r"""\1 IN ('00000000-0000-0000-0000-000000000000'::uuid)""",
        query,
    )

    # Replace notebook short_id lookups, for postgres
    query = re.sub(
        r"\"posthog_notebook\".\"short_id\" = '[a-zA-Z0-9]{8}'",
        '"posthog_notebook"."short_id" = \'00000000\'',
        query,
    )

    # Replace person id (when querying session recording replay events)
    query = re.sub(
        "and person_id = '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'",
        r"AND person_id = '00000000-0000-0000-0000-000000000000'",
        query,
        flags=re.IGNORECASE,
    )

    # HogQL person id in session recording queries
    # ifNull(equals(s__pdi.person_id, '0176be33-0398-0091-ec89-570d7768f2f4'), 0))
    # ifNull(equals(person_distinct_ids__person.id, '0176be33-0398-000c-0772-f78c97593bdd'), 0))))
    # equals(events.person_id, '0176be33-0398-0060-abed-8da43384e020')
    query = re.sub(
        r"equals\(([^.]+[._])?person.id, '[0-9a-f-]{36}'\)",
        r"equals(\1person_id, '00000000-0000-0000-0000-000000000000')",
        query,
    )

    # equals(if(not(empty(events__override.distinct_id)), events__override.person_id, events.person_id), '0176be33-0398-0090-a0e7-7cd9139f8089')
    query = re.sub(
        r"events__override.person_id, events.person_id\), '[0-9a-f-]{36}'\)",
        r"events__override.person_id, events.person_id), '00000000-0000-0000-0000-000000000000')",
        query,
    )
    query = re.sub(
        "and current_person_id = '[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'",
        r"AND current_person_id = '00000000-0000-0000-0000-000000000000'",
        query,
        flags=re.IGNORECASE,
    )

    # Replace tag id lookups for postgres
    query = re.sub(
        rf"""("posthog_tag"\."id") IN \(('[^']+'::uuid)+(, ('[^']+'::uuid)+)*\)""",
        r"""\1 IN ('00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid, '00000000-0000-0000-0000-000000000000'::uuid /* ... */)""",
        query,
    )
    query = re.sub(
        rf"""user_id:([0-9]+) request:[a-zA-Z0-9-_]+""",
        r"""user_id:0 request:_snapshot_""",
        query,
    )
    query = re.sub(
        rf"""user_id:([0-9]+)""",
        r"""user_id:0""",
        query,
    )

    # ee license check has varying datetime
    # e.g. WHERE "ee_license"."valid_until" >= '2023-03-02T21:13:59.298031+00:00'::timestamptz
    query = re.sub(
        r"ee_license\"\.\"valid_until\" >= '\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d.\d{6}\+\d\d:\d\d'::timestamptz",
        '"ee_license"."valid_until">=\'LICENSE-TIMESTAMP\'::timestamptz"',
        query,
    )

    # insight cache key varies with team id
    query = re.sub(
        r"WHERE \(\"posthog_insightcachingstate\".\"cache_key\" = 'cache_\w{32}'",
        """WHERE ("posthog_insightcachingstate"."cache_key" = 'cache_THE_CACHE_KEY'""",
        query,
    )

    # replace Savepoint numbers
    query = re.sub(r"SAVEPOINT \".+\"", "SAVEPOINT _snapshot_", query)

    # test_formula has some values that change on every run
    query = re.sub(
        r"\SELECT \[\d+, \d+] as breakdown_value",
        "SELECT [1, 2] as breakdown_value",
        query,
    )
    query = re.sub(
        r"SELECT distinct_id,[\n\r\s]+\d+ as value",
        "SELECT distinct_id, 1 as value",
        query,
    )

    # rbac has some varying IDs we can replace
    # e.g. AND "ee_accesscontrol"."resource_id" = '450'
    query = re.sub(
        r"\"resource_id\" = '\d+'",
        "\"resource_id\" = '99999'",
        query,
    )

    # project tree and file system related replacements
    query = re.sub(
        r"\"href\" = '[^']+'",
        "\"href\" = '__skipped__'",
        query,
    )

    # replace cohort calculation IDs in SQL comments and query content
    query = re.sub(
        r"/\* cohort_calculation:cohort_calc:[0-9a-f]+ \*/",
        r"/* cohort_calculation:cohort_calc:00000000 */",
        query,
    )
    query = re.sub(
        r"cohort_calc:[0-9a-f]+",
        r"cohort_calc:00000000",
        query,
    )

    # Replace dynamic event_date and event_time filters in query_log_archive queries
    query = re.sub(
        rf"event_date >= '({days_to_sub})'",
        r"event_date >= 'today'",
        query,
    )
    query = re.sub(
        rf"event_time >= '({days_to_sub}) \d\d:\d\d:\d\d'",
        r"event_time >= 'today 00:00:00'",
        query,
    )

    return query


def setup_test_organization_team_and_user(
    organization_name: str, team_api_token: str, user_email: str | None = None, user_password: str | None = None
) -> tuple[Organization, Project, Team, User | None, OrganizationMembership | None]:
    organization = Organization.objects.create(name=organization_name)
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=organization,
        api_token=team_api_token or str(uuid.uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    if user_email and user_password:
        user = User.objects.create_and_join(organization, user_email, user_password)
        organization_membership = user.organization_memberships.get()
    else:
        user = None
        organization_membership = None
    return organization, project, team, user, organization_membership


def _setup_test_data(klass):
    organization, project, team, user, organization_membership = setup_test_organization_team_and_user(
        organization_name=klass.CONFIG_ORGANIZATION_NAME,
        team_api_token=klass.CONFIG_API_TOKEN,
        user_email=klass.CONFIG_EMAIL,
        user_password=klass.CONFIG_PASSWORD,
    )
    klass.organization = organization
    klass.project = project
    klass.team = team
    klass.user = user
    klass.organization_membership = organization_membership


class FuzzyInt(int):
    """
    Some query count assertions vary depending on the order of tests in the run because values are cached and so their related query doesn't always run.

    For the purposes of testing query counts we don't care about that variation
    """

    lowest: int
    highest: int

    def __new__(cls, lowest, highest):
        obj = super().__new__(cls, highest)
        obj.lowest = lowest
        obj.highest = highest
        return obj

    def __eq__(self, other):
        return self.lowest <= other <= self.highest

    def __repr__(self):
        return f"[{self.lowest:d}..{self.highest:d}]"


class ErrorResponsesMixin:
    ERROR_INVALID_CREDENTIALS = {
        "type": "validation_error",
        "code": "invalid_credentials",
        "detail": "Invalid email or password.",
        "attr": None,
    }

    def not_found_response(self, message: str = "Not found.") -> dict[str, Optional[str]]:
        return {
            "type": "invalid_request",
            "code": "not_found",
            "detail": message,
            "attr": None,
        }

    def permission_denied_response(
        self, message: str = "You do not have permission to perform this action."
    ) -> dict[str, Optional[str]]:
        return {
            "type": "authentication_error",
            "code": "permission_denied",
            "detail": message,
            "attr": None,
        }

    def method_not_allowed_response(self, method: str) -> dict[str, Optional[str]]:
        return {
            "type": "invalid_request",
            "code": "method_not_allowed",
            "detail": f'Method "{method}" not allowed.',
            "attr": None,
        }

    def unauthenticated_response(
        self,
        message: str = "Authentication credentials were not provided.",
        code: str = "not_authenticated",
    ) -> dict[str, Optional[str]]:
        return {
            "type": "authentication_error",
            "code": code,
            "detail": message,
            "attr": None,
        }

    def validation_error_response(
        self,
        message: str = "Malformed request",
        code: str = "invalid_input",
        attr: Optional[str] = None,
    ) -> dict[str, Optional[str]]:
        return {
            "type": "validation_error",
            "code": code,
            "detail": message,
            "attr": attr,
        }


class PostHogTestCase(SimpleTestCase):
    CONFIG_ORGANIZATION_NAME: str = "Test"
    CONFIG_EMAIL: Optional[str] = "user1@posthog.com"
    CONFIG_PASSWORD: Optional[str] = "testpassword12345"
    CONFIG_API_TOKEN: str = "token123"
    CONFIG_AUTO_LOGIN: bool = True
    # Most test cases can run with class data level setup. This means that test data gets set up once per class,
    # which can greatly speed up tests. Some tests will require test data to be set up on every test case, setting this
    # to `False` will set up test data on every test case instead.
    CLASS_DATA_LEVEL_SETUP = True

    # Test data definition stubs
    organization: Organization = None
    project: Project = None
    team: Team = None
    user: User = None
    organization_membership: OrganizationMembership = None

    def _create_user(self, email: str, password: Optional[str] = None, first_name: str = "", **kwargs) -> User:
        return User.objects.create_and_join(self.organization, email, password, first_name, **kwargs)

    @classmethod
    def setUpTestData(cls):
        if cls.CLASS_DATA_LEVEL_SETUP:
            _setup_test_data(cls)

    def setUp(self):
        get_instance_setting.cache_clear()

        if get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
            from posthog.models.team import util

            util.can_enable_actor_on_events = True

        if not self.CLASS_DATA_LEVEL_SETUP:
            _setup_test_data(self)

    def tearDown(self):
        if len(persons_cache_tests) > 0:
            persons_cache_tests.clear()
            raise Exception(
                "Some persons created in this test weren't flushed, which can lead to inconsistent test results. Add flush_persons_and_events() right after creating all persons."
            )

        if len(events_cache_tests) > 0:
            events_cache_tests.clear()
            raise Exception(
                "Some events created in this test weren't flushed, which can lead to inconsistent test results. Add flush_persons_and_events() right after creating all events."
            )
        # We might be using memory cache in tests at Django level, but we also use `redis` directly in some places, so we need to clear Redis
        redis.get_client().flushdb()
        global persons_ordering_int
        persons_ordering_int = 0
        super().tearDown()

    def validate_basic_html(self, html_message, site_url, preheader=None):
        # absolute URLs are used
        self.assertIn(f"{site_url}/static/posthog-logo.png", html_message)

        # CSS is inlined
        self.assertIn('style="display: none;', html_message)

        if preheader:
            self.assertIn(preheader, html_message)

    @contextmanager
    def is_cloud(self, value: bool):
        with self.settings(CLOUD_DEPLOYMENT="US" if value else None):
            yield value

    @contextmanager
    def retry_assertion(self, max_retries=5, delay=0.1) -> Generator[None, None, None]:
        for attempt in range(max_retries):
            try:
                yield  # Only yield once per context manager instance
                return  # If we get here, the assertions passed
            except AssertionError:
                if attempt == max_retries - 1:
                    raise  # On last attempt, re-raise the assertion error
                time.sleep(delay)  # Otherwise, wait before retrying


class MemoryLeakTestMixin:
    MEMORY_INCREASE_PER_PARSE_LIMIT_B: int
    """Parsing more than once can never increase memory by this much (on average)"""
    MEMORY_INCREASE_INCREMENTAL_FACTOR_LIMIT: float
    """Parsing cannot increase memory by more than this factor * priming's increase (on average)"""
    MEMORY_PRIMING_RUNS_N: int
    """How many times to run every test method to prime the heap"""
    MEMORY_LEAK_CHECK_RUNS_N: int
    """How many times to run every test method to check for memory leaks"""

    def _callTestMethod(self, method):
        mem_original_b = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        for _ in range(self.MEMORY_PRIMING_RUNS_N):  # Priming runs
            method()
        mem_primed_b = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        for _ in range(self.MEMORY_LEAK_CHECK_RUNS_N):  # Memory leak check runs
            method()
        mem_tested_b = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        avg_memory_priming_increase_b = (mem_primed_b - mem_original_b) / self.MEMORY_PRIMING_RUNS_N
        avg_memory_test_increase_b = (mem_tested_b - mem_primed_b) / self.MEMORY_LEAK_CHECK_RUNS_N
        avg_memory_increase_factor = (
            avg_memory_test_increase_b / avg_memory_priming_increase_b if avg_memory_priming_increase_b else 0
        )
        self.assertLessEqual(
            avg_memory_test_increase_b,
            self.MEMORY_INCREASE_PER_PARSE_LIMIT_B,
            f"Possible memory leak - exceeded {self.MEMORY_INCREASE_PER_PARSE_LIMIT_B}-byte limit of incremental memory per parse",
        )
        self.assertLessEqual(
            avg_memory_increase_factor,
            self.MEMORY_INCREASE_INCREMENTAL_FACTOR_LIMIT,
            f"Possible memory leak - exceeded {self.MEMORY_INCREASE_INCREMENTAL_FACTOR_LIMIT*100:.2f}% limit of incremental memory per parse",
        )


class BaseTest(PostHogTestCase, ErrorResponsesMixin, TestCase):
    """
    Base class for performing Postgres-based backend unit tests on.
    Each class and each test is wrapped inside an atomic block to rollback DB commits after each test.
    Read more: https://docs.djangoproject.com/en/3.1/topics/testing/tools/#testcase
    """

    pass


class NonAtomicBaseTest(PostHogTestCase, ErrorResponsesMixin, TransactionTestCase):
    """
    Django wraps tests in TestCase inside atomic transactions to speed up the run time. TransactionTestCase is the base
    class for TestCase that doesn't implement this atomic wrapper.
    Read more: https://avilpage.com/2020/01/disable-transactions-django-tests.html
    """

    @classmethod
    def setUpClass(cls):
        cls.setUpTestData()

    def _fixture_teardown(self):
        # Override to use CASCADE when truncating tables.
        # Required when models are moved between Django apps, as PostgreSQL
        # needs CASCADE to handle FK constraints across app boundaries.
        from django.core.management import call_command

        for db_name in self._databases_names(include_mirrors=False):
            call_command("flush", verbosity=0, interactive=False, database=db_name, allow_cascade=True)


class APIBaseTest(PostHogTestCase, ErrorResponsesMixin, DRFTestCase):
    """
    Functional API tests using Django REST Framework test suite.
    """

    def setUp(self):
        super().setUp()

        cache.clear()
        TEST_clear_instance_license_cache()

        # Sets the cloud mode to stabilize things tests, especially num query counts
        # Clear the is_rate_limit lru_Caches so that they do not flap in test snapshots
        rate_limit.is_rate_limit_enabled.cache_clear()
        rate_limit.get_team_allow_list.cache_clear()

        if self.CONFIG_AUTO_LOGIN and self.user:
            self.client.force_login(self.user)

    def create_organization_with_features(self, features):
        organization = Organization.objects.create(name="Test Organization")
        organization.available_product_features = [{"name": feature, "key": feature} for feature in features]
        organization.save()
        return organization

    def create_team_with_organization(self, organization):
        return Team.objects.create(organization=organization, name="Test Team")

    def create_user_with_organization(self, organization):
        user = User.objects.create_user(email="testuser@example.com", first_name="Test", password="password")
        organization.members.add(user)
        return user

    def complete_email_mfa(self, email: str, user: Optional[Any] = None):
        if user is None:
            user = User.objects.get(email=email)

        token = email_mfa_token_generator.make_token(user)

        response = self.client.post("/api/login/email-mfa/", {"email": email, "token": token})

        return response

    def assertEntityResponseEqual(self, response1, response2, remove=("action", "label", "persons_urls", "filter")):
        stripped_response1 = stripResponse(response1, remove=remove)
        stripped_response2 = stripResponse(response2, remove=remove)
        self.assertDictEqual(stripped_response1[0], stripped_response2[0])

    @contextmanager
    def assertFasterThan(self, duration_ms: float):
        with assert_faster_than(duration_ms):
            yield


def stripResponse(response, remove=("action", "label", "persons_urls", "filter")):
    if len(response):
        for attr in remove:
            if attr in response[0]:
                response[0].pop(attr)
    return response


def cleanup_materialized_columns():
    try:
        from ee.clickhouse.materialized_columns.columns import get_materialized_columns
        from ee.clickhouse.materialized_columns.test.test_columns import EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS
    except:
        # EE not available? Skip
        return

    def optionally_drop(table, filter=None):
        drops = ",".join(
            [
                f"DROP COLUMN {column.name}"
                for column in get_materialized_columns(table).values()
                if filter is None or filter(column.name)
            ]
        )
        if drops:
            sync_execute(f"ALTER TABLE {table} {drops} SETTINGS mutations_sync = 2")
            if table == "events":
                sync_execute(f"ALTER TABLE sharded_events {drops} SETTINGS mutations_sync = 2")

    default_column_names = {
        get_materialized_columns("events")[(prop, "properties")].name
        for prop in EVENTS_TABLE_DEFAULT_MATERIALIZED_COLUMNS
    }

    optionally_drop("events", lambda name: name not in default_column_names)
    optionally_drop("person")
    optionally_drop("groups")


@contextmanager
def materialized(table, property, create_minmax_index: bool = False) -> Iterator[MaterializedColumn]:
    """Materialize a property within the managed block, removing it on exit."""
    try:
        from ee.clickhouse.materialized_columns.columns import get_minmax_index_name, materialize
    except ModuleNotFoundError as e:
        pytest.xfail(str(e))

    column = None
    try:
        column = materialize(table, property, create_minmax_index=create_minmax_index)
        yield column
    finally:
        if create_minmax_index and column is not None:
            data_table = "sharded_events" if table == "events" else table
            sync_execute(
                f"ALTER TABLE {data_table} DROP INDEX {get_minmax_index_name(column.name)} SETTINGS mutations_sync = 2"
            )
        cleanup_materialized_columns()


def also_test_with_materialized_columns(
    event_properties=None,
    person_properties=None,
    verify_no_jsonextract=True,
    is_nullable: Optional[list] = None,
):
    """
    Runs the test twice on clickhouse - once verifying it works normally, once with materialized columns.

    Requires a unittest class with ClickhouseTestMixin mixed in
    """

    if person_properties is None:
        person_properties = []
    if event_properties is None:
        event_properties = []
    try:
        from ee.clickhouse.materialized_columns.analyze import materialize
    except:
        # EE not available? Just run the main test
        return lambda fn: fn

    def decorator(fn):
        @pytest.mark.ee
        def fn_with_materialized(self, *args, **kwargs):
            # Don't run these tests under non-clickhouse classes even if decorated in base classes
            if not getattr(self, "RUN_MATERIALIZED_COLUMN_TESTS", False):
                return

            for prop in event_properties:
                materialize("events", prop, is_nullable=is_nullable is not None and prop in is_nullable)
            for prop in person_properties:
                materialize("person", prop, is_nullable=is_nullable is not None and prop in is_nullable)
                materialize(
                    "events",
                    prop,
                    table_column="person_properties",
                    is_nullable=is_nullable is not None and prop in is_nullable,
                )

            try:
                with self.capture_select_queries() as sqls:
                    fn(self, *args, **kwargs)
            finally:
                cleanup_materialized_columns()

            if verify_no_jsonextract:
                for sql in sqls:
                    self.assertNotIn("JSONExtract", sql)

        # To add the test, we inspect the frame this function was called in and add the test there
        frame_locals: Any = inspect.currentframe().f_back.f_locals
        frame_locals[f"{fn.__name__}_materialized"] = fn_with_materialized

        return fn

    return decorator


@pytest.mark.usefixtures("unittest_snapshot")
class QueryMatchingTest:
    snapshot: Any

    # :NOTE: Update snapshots by passing --snapshot-update to bin/tests
    def assertQueryMatchesSnapshot(self, query, params=None, replace_all_numbers=False):
        query = clean_varying_query_parts(query, replace_all_numbers)

        try:
            assert sqlparse.format(query, reindent=True) == self.snapshot
        except AssertionError:
            diff_lines = "\n".join(self.snapshot.get_assert_diff())
            error_message = f"Query does not match snapshot. Update snapshots with --snapshot-update.\n\n{diff_lines}"
            raise AssertionError(error_message)

        if params is not None:
            del params["team_id"]  # Changes every run
            try:
                assert params == self.snapshot
            except AssertionError:
                params_diff_lines = "\n".join(self.snapshot.get_assert_diff())
                params_error_message = f"Query parameters do not match snapshot. Update snapshots with --snapshot-update.\n\n{params_diff_lines}"
                raise AssertionError(params_error_message)


@contextmanager
def snapshot_postgres_queries_context(
    testcase: QueryMatchingTest,
    replace_all_numbers: bool = True,
    using: str = "default",
    capture_all_queries: bool = False,
    custom_query_matcher: Optional[Callable] = None,
):
    """
    Captures and snapshots select queries from test using `syrupy` library.
    Requires queries to be stable to avoid flakiness.

    Snapshots are automatically saved in a __snapshot__/*.ambr file.
    Update snapshots via --snapshot-update.

    To avoid flakiness, we optionally replaces all numbers in the query with a
    fixed output.

    Returns a context manager that can be used to capture queries.

    NOTE: it requires specifically that a `QueryMatchingTest` is used as the
    testcase argument.

    TODO: remove requirement that this must be used in conjunction with a
    `QueryMatchingTest` class.

    Example usage:

    class MyTest(QueryMatchingTest):
        def test_something(self):
            with snapshot_postgres_queries_context(self) as context:
                # Run some code that generates queries

    """
    with CaptureQueriesContext(connections[using]) as context:
        yield context

    for query_with_time in context.captured_queries:
        query = query_with_time["sql"]
        if custom_query_matcher:
            if query and custom_query_matcher(query):
                testcase.assertQueryMatchesSnapshot(query, replace_all_numbers=replace_all_numbers)
        elif capture_all_queries:
            testcase.assertQueryMatchesSnapshot(query, replace_all_numbers=replace_all_numbers)
        elif (
            query
            and "SELECT" in query
            and "django_session" not in query
            and not re.match(r"^\s*INSERT", query)
            and 'FROM "posthog_instancesetting"' not in query
        ):
            testcase.assertQueryMatchesSnapshot(query, replace_all_numbers=replace_all_numbers)


def snapshot_postgres_queries(fn):
    """
    Decorator that captures and snapshots select queries from test using
    `syrupy` library. It wraps `snapshot_postgres_queries_context`, see that
    context manager for more details.

    Example usage:

    class MyTest(QueryMatchingTest):
        @snapshot_postgres_queries
        def test_something(self):
            # Run some code that generates queries

    """

    @wraps(fn)
    def wrapped(self: QueryMatchingTest, *args, **kwargs):
        with snapshot_postgres_queries_context(self):
            fn(self, *args, **kwargs)

    return wrapped


class BaseTestMigrations(QueryMatchingTest):
    @property
    def app(self) -> str:
        return apps.get_containing_app_config(type(self).__module__).name

    migrate_from: str
    migrate_to: str
    apps: Optional[any] = None
    assert_snapshots = False

    def setUp(self):
        assert hasattr(self, "migrate_from") and hasattr(
            self, "migrate_to"
        ), "TestCase '{}' must define migrate_from and migrate_to properties".format(type(self).__name__)
        migrate_from = [(self.app, self.migrate_from)]
        migrate_to = [(self.app, self.migrate_to)]
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from).apps

        # Reverse to the original migration
        executor.migrate(migrate_from)

        self.setUpBeforeMigration(old_apps)

        # Run the migration to test
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()  # reload.

        if self.assert_snapshots:
            self._execute_migration_with_snapshots(executor)
        else:
            executor.migrate(migrate_to)

        self.apps = executor.loader.project_state(migrate_to).apps

    @snapshot_postgres_queries
    def _execute_migration_with_snapshots(self, executor):
        migrate_to = [(self.app, self.migrate_to)]
        executor.migrate(migrate_to)

    def setUpBeforeMigration(self, apps):
        pass

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()  # type: ignore
        executor = MigrationExecutor(connection)  # Reset Django's migration state
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)  # Migrate to the latest migration
        executor.loader.build_graph()  # Reload.


class TestMigrations(BaseTestMigrations, BaseTest):
    """
    Can be used to test migrations
    """


class NonAtomicTestMigrations(BaseTestMigrations, NonAtomicBaseTest):
    """
    Can be used to test migrations where atomic=False.
    """


def flush_persons_and_events():
    person_mapping = {}
    if len(persons_cache_tests) > 0:
        person_mapping = bulk_create_persons(persons_cache_tests)
        persons_cache_tests.clear()
    if len(events_cache_tests) > 0:
        bulk_create_events(events_cache_tests, person_mapping)
        events_cache_tests.clear()


def _create_event(**kwargs):
    """
    Create an event in tests.

    Timezone support works as follows here:
    If a `timestamp` kwarg WITHOUT an explicit timezone is provided, it's treated as local to the project.
    Example: With the default `team.timezone = 'UTC'`, timestamp `2022-11-24T12:00:00` is saved verbatim to the DB,
    as all our stored data is in UTC . However, with `team.timezone = 'America/Phoenix'`, the event will in fact be
    stored with timestamp `2022-11-24T19:00:00` - because America/Pheonix is UTC-7, and Phoenix noon occurs at 7 PM UTC.
    If a `timestamp` WITH an explicit timezone is provided (in the case of ISO strings, this can be the "Z" suffix
    signifying UTC), we use that timezone instead of the project timezone.
    If NO `timestamp` is provided, we use the current system time (which can be mocked with `freeze_time()`)
    and treat that as local to the project.

    NOTE: All events get batched and only created when sync_execute is called.
    """
    if properties := kwargs.get("properties"):
        if session_id := properties.get("$session_id"):
            _warn_if_session_id_malformed(session_id)
    if not kwargs.get("event_uuid"):
        kwargs["event_uuid"] = str(uuid.uuid4())
    if not kwargs.get("timestamp"):
        kwargs["timestamp"] = dt.datetime.now()
    events_cache_tests.append(kwargs)
    return kwargs["event_uuid"]


def _warn_if_session_id_malformed(session_id: str):
    try:
        session_id_parsed = uuid.UUID(session_id)
    except:
        print(  # noqa: T201
            f"WARNING: $session_id SHOULD be a UUIDv7 and {repr(session_id)} doesn't resemble a UUID. "
            "Events with a non-UUIDv7 session ID don't count as part of any session in HogQL-based querying. Use uuid7()!"
        )
    else:
        # You can tweak the min/max accepted times below, but don't add/subtract hundreds of years
        min_accepted_unix_time_ms = int(dt.datetime(year=2010, month=1, day=1).timestamp() * 1000)
        max_accepted_unix_time_ms = int(dt.datetime(year=2029, month=12, day=31).timestamp() * 1000)
        session_id_unix_time_ms = session_id_parsed.int >> 80
        if session_id_unix_time_ms < min_accepted_unix_time_ms:
            print(  # noqa: T201
                f"WARNING: $session_id SHOULD be a UUIDv7 and {session_id_parsed}'s value appears too small to be a UUIDv7. "
                "Events with a non-UUIDv7 session ID don't count as part of any session in HogQL-based querying. Use uuid7()!"
            )
        elif session_id_unix_time_ms > max_accepted_unix_time_ms:
            print(  # noqa: T201
                f"WARNING: $session_id SHOULD be a UUIDv7 and {session_id_parsed}'s value appears too large to be a UUIDv7. "
                "Events with a non-UUIDv7 session ID don't count as part of any session in HogQL-based querying. Use uuid7()!"
            )


def _create_person(*args, **kwargs):
    """
    Create a person in tests. NOTE: all persons get batched and only created when sync_execute is called
    Pass immediate=True to create immediately and get a pk back
    """
    global persons_ordering_int
    if not (kwargs.get("uuid")):
        kwargs["uuid"] = uuid.UUID(
            int=persons_ordering_int, version=4
        )  # make sure the ordering of uuids is always consistent
    persons_ordering_int += 1
    # If we've done freeze_time just create straight away
    if kwargs.get("immediate") or (
        hasattr(dt.datetime.now(), "__module__") and dt.datetime.now().__module__ == "freezegun.api"
    ):
        if kwargs.get("immediate"):
            del kwargs["immediate"]
        create_person(
            team_id=kwargs.get("team_id") or kwargs["team"].pk,
            properties=kwargs.get("properties"),
            uuid=kwargs["uuid"],
            version=kwargs.get("version", 0),
        )
        return Person.objects.create(**kwargs)
    if len(args) > 0:
        kwargs["distinct_ids"] = [args[0]]  # allow calling _create_person("distinct_id")

    persons_cache_tests.append(kwargs)
    return Person(**{key: value for key, value in kwargs.items() if key != "distinct_ids"})


class ClickhouseTestMixin(QueryMatchingTest):
    RUN_MATERIALIZED_COLUMN_TESTS = True
    # overrides the basetest in posthog/test/base.py
    # this way the team id will increment so we don't have to destroy all clickhouse tables on each test
    CLASS_DATA_LEVEL_SETUP = False

    snapshot: Any

    @staticmethod
    def generalize_sql(value: str):
        """Makes sure we can use inline_snapshot() for query SQL snapshots - swaps concrete team_id for placeholder."""
        if "team_id," in value:
            return re.sub(r"team_id, \d+", "team_id, <TEAM_ID>", value)
        return value

    def capture_select_queries(self):
        return self.capture_queries(lambda x: re.match(r"[\s(]*(SELECT|WITH)", x, re.I) is not None)

    def capture_queries_startswith(self, query_prefixes: Union[str, tuple[str, ...]]):
        return self.capture_queries(lambda x: x.startswith(query_prefixes))

    @contextmanager
    def capture_queries(self, query_filter: Callable[[str], bool]):
        queries = []

        def execute_wrapper(original_client_execute, query, *args, **kwargs):
            if query_filter(sqlparse.format(query, strip_comments=True).strip()):
                queries.append(query)
            return original_client_execute(query, *args, **kwargs)

        with patch_clickhouse_client_execute(execute_wrapper):
            yield queries


@contextmanager
def failhard_threadhook_context():
    """
    Context manager to ensure that exceptions raised by threads are treated as a
    test failure.
    """

    def raise_hook(args: threading.ExceptHookArgs):
        """Capture exceptions from threads and raise them as AssertionError"""
        exc = args.exc_value
        if exc is None:
            return

        # Filter out expected Kafka table errors during test setup
        if hasattr(exc, "code") and exc.code == 60 and "kafka_" in str(exc) and "posthog_test" in str(exc):
            return  # Silently ignore expected Kafka table errors

        # For other exceptions, raise as AssertionError to fail tests
        raise AssertionError from exc  # Must be an AssertionError to fail tests

    old_hook, threading.excepthook = threading.excepthook, raise_hook
    try:
        yield old_hook
    finally:
        assert threading.excepthook is raise_hook
        threading.excepthook = old_hook


def run_clickhouse_statement_in_parallel(statements: list[str]):
    jobs = []
    with failhard_threadhook_context():
        for item in statements:
            thread = threading.Thread(target=sync_execute, args=(item,))
            jobs.append(thread)

        # Start the threads (i.e. calculate the random number lists)
        for j in jobs:
            j.start()

        # Ensure all of the threads have finished
        for j in jobs:
            j.join()


def reset_clickhouse_database() -> None:
    run_clickhouse_statement_in_parallel(
        [
            DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL(),
            DROP_RAW_SESSION_MATERIALIZED_VIEW_SQL_V3(),
            DROP_RAW_SESSION_MATERIALIZED_VIEW_RECORDINGS_SQL_V3(),
            DROP_RAW_SESSION_VIEW_SQL(),
            DROP_RAW_SESSION_VIEW_SQL_V3(),
            DROP_SESSION_MATERIALIZED_VIEW_SQL(),
            DROP_SESSION_VIEW_SQL(),
            DROP_CHANNEL_DEFINITION_DICTIONARY_SQL,
            DROP_EXCHANGE_RATE_DICTIONARY_SQL(),
            DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(),
            DROP_ADHOC_EVENTS_DELETION_TABLE_SQL(),
        ]
    )
    run_clickhouse_statement_in_parallel(
        [
            DROP_CHANNEL_DEFINITION_TABLE_SQL,
            DROP_EXCHANGE_RATE_TABLE_SQL(),
            DROP_WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL(),
            DROP_DISTRIBUTED_EVENTS_TABLE_SQL,
            DROP_EVENTS_TABLE_SQL(),
            DROP_PERSON_TABLE_SQL,
            DROP_PROPERTY_DEFINITIONS_TABLE_SQL(),
            DROP_RAW_SESSION_SHARDED_TABLE_SQL(),
            DROP_RAW_SESSION_SHARDED_TABLE_SQL_V3(),
            DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL(),
            DROP_RAW_SESSION_DISTRIBUTED_TABLE_SQL_V3(),
            DROP_RAW_SESSION_WRITABLE_TABLE_SQL(),
            DROP_RAW_SESSION_WRITABLE_TABLE_SQL_V3(),
            DROP_SESSION_RECORDING_EVENTS_TABLE_SQL(),
            DROP_SESSION_REPLAY_EVENTS_TABLE_SQL(),
            DROP_SESSION_TABLE_SQL(),
            DROP_WEB_STATS_SQL(),
            DROP_WEB_BOUNCES_SQL(),
            DROP_WEB_STATS_DAILY_SQL(),
            DROP_WEB_BOUNCES_DAILY_SQL(),
            DROP_WEB_STATS_HOURLY_SQL(),
            DROP_WEB_BOUNCES_HOURLY_SQL(),
            DROP_WEB_STATS_STAGING_SQL(),
            DROP_WEB_BOUNCES_STAGING_SQL(),
            DROP_BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL(),
            DROP_BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL(),
            DROP_BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL(),
            TRUNCATE_COHORTPEOPLE_TABLE_SQL,
            TRUNCATE_EVENTS_RECENT_TABLE_SQL(),
            TRUNCATE_GROUPS_TABLE_SQL,
            TRUNCATE_PERSON_DISTINCT_ID2_TABLE_SQL,
            TRUNCATE_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL(),
            TRUNCATE_PERSON_DISTINCT_ID_TABLE_SQL,
            TRUNCATE_PERSON_STATIC_COHORT_TABLE_SQL(),
            TRUNCATE_PLUGIN_LOG_ENTRIES_TABLE_SQL,
            TRUNCATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE,
        ]
    )
    run_clickhouse_statement_in_parallel(
        [
            CHANNEL_DEFINITION_TABLE_SQL(),
            EXCHANGE_RATE_TABLE_SQL(),
            EVENTS_TABLE_SQL(),
            PERSONS_TABLE_SQL(),
            PROPERTY_DEFINITIONS_TABLE_SQL(),
            RAW_SESSIONS_TABLE_SQL(),
            SHARDED_RAW_SESSIONS_TABLE_SQL_V3(),
            WRITABLE_RAW_SESSIONS_TABLE_SQL(),
            WRITABLE_RAW_SESSIONS_TABLE_SQL_V3(),
            SESSIONS_TABLE_SQL(),
            SESSION_RECORDING_EVENTS_TABLE_SQL(),
            SESSION_REPLAY_EVENTS_TABLE_SQL(),
            CREATE_CUSTOM_METRICS_COUNTER_EVENTS_TABLE,
            WEB_BOUNCES_DAILY_SQL(),
            WEB_BOUNCES_HOURLY_SQL(),
            WEB_STATS_DAILY_SQL(),
            WEB_STATS_HOURLY_SQL(),
            WEB_STATS_SQL(),
            WEB_BOUNCES_SQL(),
            WEB_STATS_SQL(table_name="web_pre_aggregated_stats_staging"),
            WEB_BOUNCES_SQL(table_name="web_pre_aggregated_bounces_staging"),
            WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_SQL(),
            QUERY_LOG_ARCHIVE_NEW_TABLE_SQL(table_name=QUERY_LOG_ARCHIVE_DATA_TABLE),
        ]
    )
    run_clickhouse_statement_in_parallel(
        [
            CHANNEL_DEFINITION_DICTIONARY_SQL(),
            EXCHANGE_RATE_DICTIONARY_SQL(),
            DISTRIBUTED_EVENTS_TABLE_SQL(),
            DISTRIBUTED_RAW_SESSIONS_TABLE_SQL(),
            DISTRIBUTED_RAW_SESSIONS_TABLE_SQL_V3(),
            DISTRIBUTED_SESSIONS_TABLE_SQL(),
            DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(),
            DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
            CREATE_CUSTOM_METRICS_COUNTERS_VIEW,
            CUSTOM_METRICS_EVENTS_RECENT_LAG_VIEW(),
            CUSTOM_METRICS_TEST_VIEW(),
            CUSTOM_METRICS_REPLICATION_QUEUE_VIEW(),
            WEB_PRE_AGGREGATED_TEAM_SELECTION_DICTIONARY_SQL(),
            QUERY_LOG_ARCHIVE_NEW_MV_SQL(view_name=QUERY_LOG_ARCHIVE_MV, dest_table=QUERY_LOG_ARCHIVE_DATA_TABLE),
            BEHAVIORAL_COHORTS_MATCHES_SHARDED_TABLE_SQL(),
            BEHAVIORAL_COHORTS_MATCHES_WRITABLE_TABLE_SQL(),
            BEHAVIORAL_COHORTS_MATCHES_DISTRIBUTED_TABLE_SQL(),
        ]
    )
    run_clickhouse_statement_in_parallel(
        [
            CHANNEL_DEFINITION_DATA_SQL(),
            EXCHANGE_RATE_DATA_BACKFILL_SQL(),
            RAW_SESSIONS_TABLE_MV_SQL(),
            RAW_SESSIONS_TABLE_MV_SQL_V3(),
            RAW_SESSIONS_TABLE_MV_RECORDINGS_SQL_V3(),
            RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL(),
            RAW_SESSIONS_CREATE_OR_REPLACE_VIEW_SQL_V3(),
            SESSIONS_TABLE_MV_SQL(),
            SESSIONS_VIEW_SQL(),
            ADHOC_EVENTS_DELETION_TABLE_SQL(),
            CUSTOM_METRICS_VIEW(include_counters=True),
            WEB_STATS_COMBINED_VIEW_SQL(),
            WEB_PRE_AGGREGATED_TEAM_SELECTION_DATA_SQL(),
        ]
    )


class ClickhouseDestroyTablesMixin(BaseTest):
    """
    To speed up tests we normally don't destroy the tables between tests, so clickhouse tables will have data from previous tests.
    Use this mixin to make sure you completely destroy the tables between tests.
    """

    def setUp(self):
        super().setUp()
        reset_clickhouse_database()

    def tearDown(self):
        super().tearDown()
        reset_clickhouse_database()


def snapshot_clickhouse_queries(fn_or_class):
    """
    Captures and snapshots SELECT queries from test using `syrupy` library.

    Requires queries to be stable to avoid flakiness.

    Snapshots are automatically saved in a __snapshot__/*.ambr file.
    Update snapshots via --snapshot-update.
    """

    # check if fn_or_class is a class
    if inspect.isclass(fn_or_class):
        # wrap every class method that starts with test_ with this decorator
        for attr in dir(fn_or_class):
            if callable(getattr(fn_or_class, attr)) and attr.startswith("test_"):
                setattr(fn_or_class, attr, snapshot_clickhouse_queries(getattr(fn_or_class, attr)))
        return fn_or_class

    @wraps(fn_or_class)
    def wrapped(self, *args, **kwargs):
        with self.capture_select_queries() as queries:
            fn_or_class(self, *args, **kwargs)

        for query in queries:
            if "FROM system.columns" not in query:
                replace_all_numbers = getattr(self, "snapshot_replace_all_numbers", False)
                self.assertQueryMatchesSnapshot(query, replace_all_numbers=replace_all_numbers)

    return wrapped


def snapshot_clickhouse_alter_queries(fn):
    """
    Captures and snapshots ALTER queries from test using `syrupy` library.
    """

    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.capture_queries_startswith("ALTER") as queries:
            fn(self, *args, **kwargs)

        for query in queries:
            if "FROM system.columns" not in query:
                self.assertQueryMatchesSnapshot(query, replace_all_numbers=True)

    return wrapped


def snapshot_clickhouse_insert_cohortpeople_queries(fn):
    """
    Captures and snapshots INSERT queries from test using `syrupy` library.
    """

    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.capture_queries_startswith("INSERT INTO cohortpeople") as queries:
            fn(self, *args, **kwargs)

        for query in queries:
            if "FROM system.columns" not in query:
                self.assertQueryMatchesSnapshot(query)

    return wrapped


def snapshot_hogql_queries(fn_or_class):
    """
    Captures and snapshots HogQL queries from test using `syrupy` library.

    This decorator captures queries at the point they are built (before resolution)
    and converts them to simple HogQL syntax with virtual tables like session.$entry_pathname.

    Snapshots are automatically saved in a __snapshot__/*.ambr file.
    Update snapshots via --snapshot-update.

    Example:
        @snapshot_hogql_queries
        def test_my_query(self):
            # Your test code that executes HogQL queries
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            runner.calculate()
    """
    # check if fn_or_class is a class
    if inspect.isclass(fn_or_class):
        # wrap every class method that starts with test_ with this decorator
        for attr in dir(fn_or_class):
            if callable(getattr(fn_or_class, attr)) and attr.startswith("test_"):
                setattr(fn_or_class, attr, snapshot_hogql_queries(getattr(fn_or_class, attr)))
        return fn_or_class

    @wraps(fn_or_class)
    def wrapped(self, *args, **kwargs):
        captured_queries = []

        # Patch the execute_hogql_query method on the paginator to capture queries before resolution
        original_paginator_method = HogQLHasMorePaginator.execute_hogql_query

        def capture_paginator_execute(paginator_self, query, **exec_kwargs):
            # Capture the query AST before it gets resolved
            if isinstance(query, ast.SelectQuery | ast.SelectSetQuery):
                captured_queries.append(clone_expr(query))

            return original_paginator_method(paginator_self, query=query, **exec_kwargs)

        # Patch the module-level execute_hogql_query function for direct calls
        # We need to patch it in modules that import it directly
        original_module_function = hogql_query_module.execute_hogql_query

        def capture_module_execute(*exec_args, **exec_kwargs):
            # Extract the query parameter - it can be positional or keyword
            query = exec_kwargs.get("query") if "query" in exec_kwargs else (exec_args[0] if exec_args else None)

            # Capture the query AST before it gets resolved
            if query and isinstance(query, ast.SelectQuery | ast.SelectSetQuery):
                captured_queries.append(clone_expr(query))

            return original_module_function(*exec_args, **exec_kwargs)

        # Import modules that use execute_hogql_query directly
        patches = [
            patch.object(HogQLHasMorePaginator, "execute_hogql_query", capture_paginator_execute),
            patch.object(hogql_query_module, "execute_hogql_query", capture_module_execute),
        ]

        # Add patches for modules that import execute_hogql_query directly
        try:
            from posthog.hogql_queries.web_analytics import web_overview

            if hasattr(web_overview, "execute_hogql_query"):
                patches.append(patch.object(web_overview, "execute_hogql_query", capture_module_execute))
        except ImportError:
            pass

        try:
            from posthog.hogql_queries.web_analytics import stats_table

            if hasattr(stats_table, "execute_hogql_query"):
                patches.append(patch.object(stats_table, "execute_hogql_query", capture_module_execute))
        except ImportError:
            pass

        try:
            from posthog.hogql_queries.insights.trends import trends_query_runner

            if hasattr(trends_query_runner, "execute_hogql_query"):
                patches.append(patch.object(trends_query_runner, "execute_hogql_query", capture_module_execute))
        except ImportError:
            pass

        # Apply all patches
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            fn_or_class(self, *args, **kwargs)

        # Convert each captured query to HogQL and snapshot it
        for query_ast in captured_queries:
            # Use prepare_and_print_ast with hogql dialect to get the simple logical view
            context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
            hogql, _ = prepare_and_print_ast(query_ast, context=context, dialect="hogql")

            # Format the HogQL query for better readability
            formatted_hogql = hogql.strip()

            # Use a custom snapshot with .hogql extension to separate from ClickHouse snapshots
            # This creates a separate file like test_foo.hogql.ambr instead of test_foo.ambr
            assert formatted_hogql == self.snapshot(extension_class=HogQLSnapshotExtension)

    return wrapped


class HogQLSnapshotExtension(AmberSnapshotExtension):
    """Custom syrupy extension for HogQL snapshots to use separate files."""

    _file_extension = "hogql.ambr"

    @classmethod
    def serialize(cls, data, **kwargs):
        """Serialize the HogQL query."""
        # Format the query for readability
        formatted = sqlparse.format(data, reindent=True)
        return f"'''\n{formatted}\n'''\n"


def also_test_with_different_timezones(fn):
    """
    Runs the test thrice: 1. with UTC as the project timezone, 2. with UTC-7, 3. with UTC+9.
    This is intended for catching bugs around timezone handling.
    """

    def fn_minus_utc(self, *args, **kwargs):
        self.team.timezone = "America/Phoenix"  # UTC-7. Arizona does not observe DST, which is good for determinism
        self.team.save()
        fn(self, *args, **kwargs)

    def fn_plus_utc(self, *args, **kwargs):
        self.team.timezone = "Asia/Tokyo"  # UTC+9. Japan does not observe DST, which is good for determinism
        self.team.save()
        fn(self, *args, **kwargs)

    # To add the test, we inspect the frame this function was called in and add the test there
    frame_locals: Any = inspect.currentframe().f_back.f_locals
    frame_locals[f"{fn.__name__}_minus_utc"] = fn_minus_utc
    frame_locals[f"{fn.__name__}_plus_utc"] = fn_plus_utc

    return fn


def also_test_with_person_on_events_v2(fn):
    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def fn_with_poe_v2(self, *args, **kwargs):
        fn(self, *args, **kwargs)

    # To add the test, we inspect the frame this function was called in and add the test there
    frame_locals: Any = inspect.currentframe().f_back.f_locals
    frame_locals[f"{fn.__name__}_poe_v2"] = fn_with_poe_v2

    return fn


@contextmanager
def patch_clickhouse_client_execute(execute_wrapper):
    @contextmanager
    def get_client(orig_fn, *args, **kwargs):
        with orig_fn(*args, **kwargs) as client:
            original_client_execute = client.execute
            wrapped_execute = lambda query, *args, **kwargs: execute_wrapper(
                original_client_execute, query, *args, **kwargs
            )
            with patch.object(client, "execute", wraps=wrapped_execute) as _:
                yield client

    with get_client_from_pool._temp_patch(get_client):
        yield


def _create_insight(
    team: Team, insight_filters: dict[str, Any], dashboard_filters: dict[str, Any]
) -> tuple[Insight, Dashboard, DashboardTile]:
    dashboard = Dashboard.objects.create(team=team, filters=dashboard_filters)
    insight = Insight.objects.create(team=team, filters=insight_filters)
    dashboard_tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
    return insight, dashboard, dashboard_tile


# Populate the person_overrides table with an override from the person_id
# for a person with a given distinct ID `distinct_id_from` to a given distinct ID
# `distinct_id_to` such that with person_on_events_mode set to V2_ENABLED these
# persons will both count as 1
def create_person_id_override_by_distinct_id(
    distinct_id_from: str, distinct_id_to: str, team_id: int, version: int = 0
):
    # XXX: No guarantees that data has been written to ``person_distinct_id2``
    # in tests, so just assume that the data in ``events`` is up-to-date.
    person_ids_result = sync_execute(
        f"""
        SELECT DISTINCT person_id
        FROM events
        WHERE team_id = {team_id} AND distinct_id = '{distinct_id_to}'
        """
    )

    [person_id_to] = person_ids_result[0]

    sync_execute(
        f"""
        INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version)
        VALUES ({team_id}, '{distinct_id_from}', '{person_id_to}', {version})
    """
    )
