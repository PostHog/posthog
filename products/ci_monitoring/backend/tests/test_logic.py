import io
import re
import zipfile

import pytest

from django.utils import timezone

import responses

from products.ci_monitoring.backend import github_integration, logic
from products.ci_monitoring.backend.facade.enums import TestExecutionStatus
from products.ci_monitoring.backend.junit_parser import ParsedTestResult
from products.ci_monitoring.backend.models import CIRun, TestCase, TestExecution


@pytest.mark.django_db
class TestIngestTestResults:
    def test_creates_test_cases_and_executions(self, ci_run):
        results = [
            ParsedTestResult("mod.test_a", "mod", "test_a", TestExecutionStatus.PASSED, 100, None, 0, "test.py"),
            ParsedTestResult(
                "mod.test_b", "mod", "test_b", TestExecutionStatus.FAILED, 200, "AssertionError", 0, "test.py"
            ),
            ParsedTestResult("mod.test_c", "mod", "test_c", TestExecutionStatus.FLAKY, 300, "Timeout", 2, "test.py"),
            ParsedTestResult("mod.test_d", "mod", "test_d", TestExecutionStatus.SKIPPED, 0, None, 0, "test.py"),
            ParsedTestResult("mod.test_e", "mod", "test_e", TestExecutionStatus.ERROR, 0, "Infra", 0, "test.py"),
        ]

        logic.ingest_test_results(ci_run=ci_run, parsed_results=results)

        assert TestCase.objects.filter(repo=ci_run.repo).count() == 5
        assert TestExecution.objects.filter(ci_run=ci_run).count() == 5

        ci_run.refresh_from_db()
        assert ci_run.total_tests == 5
        assert ci_run.passed == 1
        assert ci_run.failed == 1
        assert ci_run.flaky == 1
        assert ci_run.skipped == 1
        assert ci_run.errored == 1
        assert ci_run.artifacts_ingested is True

    def test_flaky_updates_last_flaked_at(self, ci_run):
        results = [
            ParsedTestResult("mod.test_f", "mod", "test_f", TestExecutionStatus.FLAKY, 100, "Timeout", 1, None),
        ]

        logic.ingest_test_results(ci_run=ci_run, parsed_results=results)

        tc = TestCase.objects.get(identifier="mod.test_f")
        assert tc.last_flaked_at is not None

    def test_deduplicates_test_cases_across_runs(self, repo):
        now = timezone.now()
        run1 = CIRun.objects.create(
            team_id=repo.team_id,
            repo=repo,
            github_run_id=1,
            workflow_name="CI",
            commit_sha="aaa",
            branch="main",
            conclusion="success",
            started_at=now,
            completed_at=now,
        )
        run2 = CIRun.objects.create(
            team_id=repo.team_id,
            repo=repo,
            github_run_id=2,
            workflow_name="CI",
            commit_sha="bbb",
            branch="main",
            conclusion="success",
            started_at=now,
            completed_at=now,
        )

        result = [ParsedTestResult("mod.test_x", "mod", "test_x", TestExecutionStatus.PASSED, 50, None, 0, None)]
        logic.ingest_test_results(ci_run=run1, parsed_results=result)
        logic.ingest_test_results(ci_run=run2, parsed_results=result)

        assert TestCase.objects.filter(identifier="mod.test_x").count() == 1
        assert TestExecution.objects.filter(test_case__identifier="mod.test_x").count() == 2


@pytest.mark.django_db
class TestMainStreak:
    def test_success_starts_streak(self, repo):
        streak = logic.record_main_branch_run(
            repo_id=repo.id, team_id=repo.team_id, conclusion="success", workflow_name="CI"
        )
        assert streak.current_streak_started_at is not None

    def test_failure_breaks_streak(self, repo):
        logic.record_main_branch_run(repo_id=repo.id, team_id=repo.team_id, conclusion="success", workflow_name="CI")
        streak = logic.record_main_branch_run(
            repo_id=repo.id, team_id=repo.team_id, conclusion="failure", workflow_name="CI"
        )

        assert streak.current_streak_started_at is None
        assert streak.last_broken_at is not None
        assert "CI" in streak.last_incident_workflows

    def test_recovery_after_failure(self, repo):
        logic.record_main_branch_run(repo_id=repo.id, team_id=repo.team_id, conclusion="failure", workflow_name="CI")
        streak = logic.record_main_branch_run(
            repo_id=repo.id, team_id=repo.team_id, conclusion="success", workflow_name="CI"
        )

        assert streak.current_streak_started_at is not None
        assert streak.last_incident_workflows == []

    def test_record_streak_updates(self, repo):
        import datetime

        streak = logic.get_or_create_main_streak(repo_id=repo.id, team_id=repo.team_id)
        streak.current_streak_started_at = timezone.now() - datetime.timedelta(days=10)
        streak.save()

        logic.record_main_branch_run(repo_id=repo.id, team_id=repo.team_id, conclusion="failure", workflow_name="CI")

        streak.refresh_from_db()
        assert streak.record_streak_days >= 10


@pytest.mark.django_db
class TestFlakeScores:
    def test_computes_correct_scores(self, repo):
        now = timezone.now()
        tc = TestCase.objects.create(team_id=repo.team_id, repo=repo, identifier="mod.flaky_test")

        # Each execution needs its own CIRun (unique constraint on ci_run+test_case)
        for i in range(10):
            run = CIRun.objects.create(
                team_id=repo.team_id,
                repo=repo,
                github_run_id=1000 + i,
                workflow_name="CI",
                commit_sha=f"sha{i}",
                branch="main",
                conclusion="success",
                started_at=now,
                completed_at=now,
            )
            status = TestExecutionStatus.FLAKY if i < 3 else TestExecutionStatus.PASSED
            TestExecution.objects.create(ci_run=run, test_case=tc, status=status)

        logic.update_flake_scores(repo_id=repo.id, team_id=repo.team_id)

        tc.refresh_from_db()
        assert tc.flake_score == 30.0
        assert tc.total_runs == 10
        assert tc.total_flakes == 3

    def test_zero_executions_unchanged(self, repo):
        tc = TestCase.objects.create(team_id=repo.team_id, repo=repo, identifier="mod.no_runs")

        logic.update_flake_scores(repo_id=repo.id, team_id=repo.team_id)

        tc.refresh_from_db()
        assert tc.flake_score == 0.0


@pytest.mark.django_db
class TestDownloadRunArtifacts:
    @responses.activate
    def test_downloads_and_extracts_junit_xml(self, ci_run, mock_github_integration):
        # Create a zip containing a JUnit XML file
        xml_content = b'<testsuite><testcase classname="a" name="b" time="0.1"/></testsuite>'
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("junit-core.xml", xml_content)
        zip_bytes = zip_buffer.getvalue()

        responses.add(
            responses.GET,
            re.compile(r".*/actions/runs/\d+/artifacts"),
            json={
                "artifacts": [{"name": "junit-results", "archive_download_url": "https://api.github.com/download/1"}]
            },
        )
        responses.add(responses.GET, "https://api.github.com/download/1", body=zip_bytes)

        result = github_integration.download_run_artifacts(ci_run)

        assert len(result) == 1
        assert b"testcase" in result[0]

    @responses.activate
    def test_skips_non_junit_artifacts(self, ci_run, mock_github_integration):
        responses.add(
            responses.GET,
            re.compile(r".*/actions/runs/\d+/artifacts"),
            json={
                "artifacts": [{"name": "coverage-report", "archive_download_url": "https://api.github.com/download/2"}]
            },
        )

        result = github_integration.download_run_artifacts(ci_run)

        assert len(result) == 0
