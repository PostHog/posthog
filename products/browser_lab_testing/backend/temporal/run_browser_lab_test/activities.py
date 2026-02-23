import re
from dataclasses import dataclass, field

from django.db import close_old_connections
from django.utils import timezone

from playwright.sync_api import sync_playwright
from temporalio import activity

_SECRETS_PATTERN = re.compile(r"\{\{secrets\.(\w+)\}\}")


def _resolve_placeholders(value: str, secrets: dict[str, str]) -> str:
    return _SECRETS_PATTERN.sub(lambda m: secrets.get(m.group(1), m.group(0)), value)


def _resolve_step(step: dict, secrets: dict[str, str]) -> dict:
    return {k: _resolve_placeholders(v, secrets) if isinstance(v, str) else v for k, v in step.items()}


@dataclass
class FetchBrowserLabTestActivityInput:
    browser_lab_test_id: str
    browser_lab_test_run_id: str


@dataclass
class FetchBrowserLabTestActivityOutput:
    url: str
    steps: list
    browser_lab_test_run_id: str
    secrets: dict = field(default_factory=dict)


@dataclass
class RunBrowserLabTestActivityInput:
    url: str
    steps: list
    browser_lab_test_run_id: str
    secrets: dict = field(default_factory=dict)


@dataclass
class RunBrowserLabTestActivityOutput:
    success: bool
    error: str | None = None


@activity.defn
def fetch_browser_lab_test_activity(input: FetchBrowserLabTestActivityInput) -> FetchBrowserLabTestActivityOutput:
    close_old_connections()

    from products.browser_lab_testing.backend.models import BrowserLabTest, BrowserLabTestRun

    lab_test = BrowserLabTest.objects.get(id=input.browser_lab_test_id)
    BrowserLabTestRun.objects.filter(id=input.browser_lab_test_run_id).update(
        status=BrowserLabTestRun.Status.RUNNING,
    )

    return FetchBrowserLabTestActivityOutput(
        url=lab_test.url,
        steps=lab_test.steps,
        browser_lab_test_run_id=input.browser_lab_test_run_id,
        secrets=lab_test.encrypted_secrets or {},
    )


@activity.defn
def run_browser_lab_test_activity(input: RunBrowserLabTestActivityInput) -> RunBrowserLabTestActivityOutput:
    page_title = ""
    final_url = ""

    secrets = input.secrets
    resolved_url = _resolve_placeholders(input.url, secrets)
    resolved_steps = [_resolve_step(step, secrets) for step in input.steps]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                ],
            )
            try:
                context = browser.new_context()
                page = context.new_page()

                page.goto(resolved_url, wait_until="domcontentloaded", timeout=30_000)

                for step in resolved_steps:
                    action = step.get("action")
                    if action == "navigate":
                        page.goto(step["url"], wait_until="domcontentloaded", timeout=30_000)
                    elif action == "click":
                        page.click(step["selector"], timeout=10_000)
                    elif action == "type":
                        page.fill(step["selector"], step["text"], timeout=10_000)
                    elif action == "waitForSelector":
                        page.wait_for_selector(step["selector"], timeout=10_000)
                    elif action == "waitForNavigation":
                        page.wait_for_load_state("domcontentloaded", timeout=30_000)

                page_title = page.title()
                final_url = page.url

                context.close()
            finally:
                browser.close()
    except Exception as e:
        close_old_connections()
        from products.browser_lab_testing.backend.models import BrowserLabTestRun

        BrowserLabTestRun.objects.filter(id=input.browser_lab_test_run_id).update(
            status=BrowserLabTestRun.Status.FAILED,
            error=str(e),
            finished_at=timezone.now(),
        )
        return RunBrowserLabTestActivityOutput(success=False, error=str(e))

    close_old_connections()
    from products.browser_lab_testing.backend.models import BrowserLabTestRun

    BrowserLabTestRun.objects.filter(id=input.browser_lab_test_run_id).update(
        status=BrowserLabTestRun.Status.COMPLETED,
        result={"page_title": page_title, "final_url": final_url},
        finished_at=timezone.now(),
    )
    return RunBrowserLabTestActivityOutput(success=True)
