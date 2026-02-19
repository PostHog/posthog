from dataclasses import dataclass

from django.utils import timezone

from temporalio import activity


@dataclass
class RunBrowserLabTestActivityInput:
    team_id: int
    browser_lab_test_id: str
    browser_lab_test_run_id: str
    url: str
    steps: list


@dataclass
class RunBrowserLabTestActivityOutput:
    success: bool
    error: str | None = None


@activity.defn
async def run_browser_lab_test_activity(input: RunBrowserLabTestActivityInput) -> RunBrowserLabTestActivityOutput:
    from products.browser_lab_testing.backend.models import BrowserLabTestRun

    await BrowserLabTestRun.objects.filter(id=input.browser_lab_test_run_id).aupdate(
        status=BrowserLabTestRun.Status.COMPLETED,
        finished_at=timezone.now(),
    )

    return RunBrowserLabTestActivityOutput(success=True)
