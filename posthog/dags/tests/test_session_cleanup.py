from datetime import timedelta

import pytest
from freezegun import freeze_time

from django.contrib.sessions.models import Session
from django.utils import timezone

from dagster import build_op_context

from posthog.dags.session_cleanup import (
    ExpiredSessionCleanupConfig,
    clean_expired_sessions,
    expired_session_cleanup_job,
)


def create_session(expire_date: timezone.datetime) -> Session:
    session = Session(
        session_key=f"test_session_{expire_date.isoformat()}",
        session_data="test_data",
        expire_date=expire_date,
    )
    session.save()
    return session


class TestCleanExpiredSessionsOp:
    @pytest.mark.django_db
    @freeze_time("2024-01-15 12:00:00")
    def test_deletes_sessions_expired_more_than_7_days_ago(self):
        expired_8_days = create_session(timezone.now() - timedelta(days=8))
        expired_7_days_1_sec = create_session(timezone.now() - timedelta(days=7, seconds=1))

        context = build_op_context()
        result = clean_expired_sessions(context, ExpiredSessionCleanupConfig(days_expired=7))

        assert result == 2
        assert not Session.objects.filter(session_key=expired_8_days.session_key).exists()
        assert not Session.objects.filter(session_key=expired_7_days_1_sec.session_key).exists()

    @pytest.mark.django_db
    @freeze_time("2024-01-15 12:00:00")
    def test_keeps_sessions_expired_7_days_or_less(self):
        expired_exactly_7_days = create_session(timezone.now() - timedelta(days=7))
        expired_6_days = create_session(timezone.now() - timedelta(days=6))
        expired_1_day = create_session(timezone.now() - timedelta(days=1))

        context = build_op_context()
        result = clean_expired_sessions(context, ExpiredSessionCleanupConfig(days_expired=7))

        assert result == 0
        assert Session.objects.filter(session_key=expired_exactly_7_days.session_key).exists()
        assert Session.objects.filter(session_key=expired_6_days.session_key).exists()
        assert Session.objects.filter(session_key=expired_1_day.session_key).exists()

    @pytest.mark.django_db
    @freeze_time("2024-01-15 12:00:00")
    def test_keeps_sessions_not_yet_expired(self):
        not_expired = create_session(timezone.now() + timedelta(days=1))
        expires_in_7_days = create_session(timezone.now() + timedelta(days=7))

        context = build_op_context()
        result = clean_expired_sessions(context, ExpiredSessionCleanupConfig(days_expired=7))

        assert result == 0
        assert Session.objects.filter(session_key=not_expired.session_key).exists()
        assert Session.objects.filter(session_key=expires_in_7_days.session_key).exists()

    @pytest.mark.django_db
    @freeze_time("2024-01-15 12:00:00")
    def test_deletes_multiple_stale_sessions(self):
        stale_sessions = [
            create_session(timezone.now() - timedelta(days=10)),
            create_session(timezone.now() - timedelta(days=14)),
            create_session(timezone.now() - timedelta(days=30)),
        ]
        fresh_session = create_session(timezone.now() - timedelta(days=3))

        context = build_op_context()
        result = clean_expired_sessions(context, ExpiredSessionCleanupConfig(days_expired=7))

        assert result == 3
        for session in stale_sessions:
            assert not Session.objects.filter(session_key=session.session_key).exists()
        assert Session.objects.filter(session_key=fresh_session.session_key).exists()

    @pytest.mark.django_db
    def test_handles_empty_table(self):
        Session.objects.all().delete()

        context = build_op_context()
        result = clean_expired_sessions(context, ExpiredSessionCleanupConfig(days_expired=7))

        assert result == 0
        assert Session.objects.count() == 0

    @pytest.mark.django_db
    @freeze_time("2024-01-15 12:00:00")
    def test_adds_metadata(self):
        create_session(timezone.now() - timedelta(days=10))
        create_session(timezone.now() - timedelta(days=14))

        context = build_op_context()
        clean_expired_sessions(context, ExpiredSessionCleanupConfig(days_expired=7))

        metadata = context.get_output_metadata("result")
        assert metadata["deleted_count"].value == 2


class TestExpiredSessionCleanupJob:
    @pytest.mark.django_db
    @freeze_time("2024-01-15 12:00:00")
    def test_job_execution_success(self):
        stale_session = create_session(timezone.now() - timedelta(days=10))
        fresh_session = create_session(timezone.now() - timedelta(days=3))

        result = expired_session_cleanup_job.execute_in_process(
            run_config={"ops": {"clean_expired_sessions": {"config": {"days_expired": 7}}}}
        )

        assert result.success
        assert not Session.objects.filter(session_key=stale_session.session_key).exists()
        assert Session.objects.filter(session_key=fresh_session.session_key).exists()
