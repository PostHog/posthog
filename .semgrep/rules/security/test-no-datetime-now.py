# Test cases for test-no-datetime-now rule
# This file is used by `semgrep --test` to verify the rule works correctly.
#
# Note: This rule only applies to test files, but semgrep's test framework runs
# tests against this .py file directly, so we test the patterns here.
# ruff: noqa: F841 — assignments exist solely to give semgrep something to match

import datetime as dt
from datetime import date, datetime

import pytest
import time_machine

from django.utils import (
    timezone,
    timezone as django_timezone,
)

# ============================================================
# Should flag: time-dependent calls in tests without a frozen clock
# ============================================================


class TestWithoutFreeze:
    def test_bare_datetime_now(self):
        # ruleid: test-datetime-now-without-freeze
        now = datetime.now()

    def test_bare_datetime_utcnow(self):
        # ruleid: test-datetime-now-without-freeze
        now = datetime.utcnow()

    def test_bare_datetime_today(self):
        # ruleid: test-datetime-now-without-freeze
        now = datetime.today()

    def test_bare_timezone_now(self):
        # ruleid: test-datetime-now-without-freeze
        now = timezone.now()

    def test_bare_django_timezone_now(self):
        # ruleid: test-datetime-now-without-freeze
        now = django_timezone.now()

    def test_bare_date_today(self):
        # ruleid: test-datetime-now-without-freeze
        today = date.today()

    def test_bare_dt_datetime_now(self):
        # ruleid: test-datetime-now-without-freeze
        now = dt.datetime.now()

    def test_bare_dt_datetime_utcnow(self):
        # ruleid: test-datetime-now-without-freeze
        now = dt.datetime.utcnow()

    def test_bare_dt_datetime_today(self):
        # ruleid: test-datetime-now-without-freeze
        now = dt.datetime.today()

    def test_bare_dt_date_today(self):
        # ruleid: test-datetime-now-without-freeze
        today = dt.date.today()


# ============================================================
# Should NOT flag: protected by @time_machine.travel on method
# ============================================================


class TestWithFreezeOnMethod:
    @time_machine.travel("2024-01-01", tick=False)
    def test_frozen_datetime_now(self):
        # ok: test-datetime-now-without-freeze
        now = datetime.now()

    @time_machine.travel("2024-01-01", tick=False)
    def test_frozen_timezone_now(self):
        # ok: test-datetime-now-without-freeze
        now = timezone.now()

    @time_machine.travel("2024-01-01", tick=False)
    def test_frozen_dt_datetime_now(self):
        # ok: test-datetime-now-without-freeze
        now = dt.datetime.now()


# ============================================================
# Should NOT flag: protected by @time_machine.travel on class
# ============================================================


@time_machine.travel("2024-01-01", tick=False)
class TestWithFreezeOnClass:
    def test_class_frozen_datetime_now(self):
        # ok: test-datetime-now-without-freeze
        now = datetime.now()

    def test_class_frozen_timezone_now(self):
        # ok: test-datetime-now-without-freeze
        now = timezone.now()


@time_machine.travel("2024-01-01", tick=False)
class TestWithFreezeOnClassWithBases:
    def test_class_frozen_with_bases(self):
        # ok: test-datetime-now-without-freeze
        now = datetime.now()


# ============================================================
# Should NOT flag: protected by an autouse fixture that travels
# ============================================================


class TestWithAutouseFixture:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-01-01", tick=False):
            yield

    def test_fixture_frozen_datetime_now(self):
        # ok: test-datetime-now-without-freeze
        now = datetime.now()

    def test_fixture_frozen_date_today(self):
        # ok: test-datetime-now-without-freeze
        today = date.today()


class ClockMixin:
    pass


class TestWithAutouseFixtureAndBases(ClockMixin):
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-01-01", tick=False):
            yield

    def test_fixture_frozen_with_bases(self):
        # ok: test-datetime-now-without-freeze
        now = datetime.now()


# ============================================================
# Should NOT flag: protected by @time_machine.travel on stacked decorators
# ============================================================


class TestWithStackedDecorators:
    @time_machine.travel("2024-01-01", tick=False)
    def test_stacked_frozen_datetime_now(self):
        # ok: test-datetime-now-without-freeze
        now = datetime.now()


# ============================================================
# Should NOT flag: protected by with time_machine.travel() context manager
# ============================================================


class TestWithFreezeContextManager:
    def test_context_manager_datetime_now(self):
        with time_machine.travel("2024-01-01", tick=False):
            # ok: test-datetime-now-without-freeze
            now = datetime.now()

    def test_context_manager_timezone_now(self):
        with time_machine.travel("2024-01-01", tick=False):
            # ok: test-datetime-now-without-freeze
            now = timezone.now()

    def test_context_manager_with_binding(self):
        with time_machine.travel("2024-01-01", tick=False) as frozen_time:
            # ok: test-datetime-now-without-freeze
            now = datetime.now()


# ============================================================
# Should NOT flag: not a test method
# ============================================================


class TestHelpers:
    def helper_get_time(self):
        # ok: test-datetime-now-without-freeze
        return datetime.now()

    def setUp(self):
        # ok: test-datetime-now-without-freeze
        self.now = datetime.now()
