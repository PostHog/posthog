import asyncio
import datetime as dt
import os
import random
import subprocess
from pathlib import Path
from typing import Literal, Optional
from dataclasses import dataclass
import urllib.parse

import aiohttp
from aiohttp import ClientTimeout


from playwright.async_api import async_playwright
from posthog.demo.matrix.models import SimEvent
from posthog.demo.products.hedgebox.models import HedgeboxPerson
from posthog.demo.products.hedgebox.taxonomy import (
    EVENT_SIGNED_UP,
    EVENT_LOGGED_IN,
    EVENT_UPLOADED_FILE,
    EVENT_DOWNLOADED_FILE,
    EVENT_DELETED_FILE,
)


@dataclass
class ReplayableSession:
    """A session that can be replayed with Playwright."""

    person: HedgeboxPerson
    events: list[SimEvent]
    start_time: dt.datetime
    end_time: dt.datetime


LOCAL_POSTHOG_NETLOC = "localhost:8010"
WEB_APP_NETLOC = "localhost:3000"


class SessionReplayGenerator:
    """Generates session recordings by replaying simulated user behavior with Playwright."""

    product_key: Literal["hedgebox"]  # Only Hedgebox is supported for now
    product_app_path: Path
    posthog_api_token: str
    max_sessions: int
    headless: bool
    _app_process: Optional[subprocess.Popen] = None

    def __init__(
        self,
        product_key: Literal["hedgebox"],
        posthog_api_token: str,
        *,
        max_sessions: int = 2,
        headless: bool = False,
    ):
        self.product_key = product_key
        self.product_app_path = Path(__file__).parent.parent / "products" / product_key / "app"
        self.posthog_api_token = posthog_api_token
        self.max_sessions = max_sessions
        self.headless = headless

    async def generate_session_recordings(self, people: list[HedgeboxPerson], *, print_progress: bool = False) -> None:
        """Generate session replays for a sample of sessions of the given simulated users."""
        if print_progress:
            print("Starting the Hedgebox app in the background...")
        self.start_demo_app(print_progress=print_progress)

        if print_progress:
            print("Selecting sessions for replay generation...")
        replayable_sessions = self._select_sessions_for_replay(people)

        if print_progress:
            print(f"Selected {len(replayable_sessions)} sessions for replay")

        if print_progress:
            print("Waiting for the Hedgebox app to be ready...")
        await self._wait_for_netloc_ready(WEB_APP_NETLOC)  # Next.js app should be ready by now
        await self._wait_for_netloc_ready(LOCAL_POSTHOG_NETLOC)

        try:
            if print_progress:
                print("Beginning session replay automation...")
            await self._replay_sessions(replayable_sessions, print_progress)
        except:
            raise
        finally:
            await self._stop_demo_app()
            if print_progress:
                print("Session replay generation completed")

    def _select_sessions_for_replay(self, people: list[HedgeboxPerson]) -> list[ReplayableSession]:
        """Select a sample of Chrome sessions for recording."""
        sessions = []
        for person in people:
            # Filter for Chrome users only, as we'll be capturing the web app in Chrome using Playwright
            if person.active_client.browser != "Chrome":
                continue
            sessions.extend(self._group_events_into_sessions(person))
        return random.sample(sessions, min(self.max_sessions, len(sessions)))

    def _group_events_into_sessions(self, person: HedgeboxPerson) -> list[ReplayableSession]:
        """Group a person's events into sessions based on $session_id."""
        if not person.all_events:
            return []
        # Group events by $session_id
        sessions_by_id: dict[str, list[SimEvent]] = {}
        for event in person.all_events:
            session_id = event.properties.get("$session_id")
            if session_id is None:
                continue  # Unexpected, but we'll skip it
            sessions_by_id.setdefault(session_id, []).append(event)
        return [
            ReplayableSession(
                person=person, events=events, start_time=events[0].timestamp, end_time=events[-1].timestamp
            )
            for events in sessions_by_id.values()
        ]

    def start_demo_app(self, *, print_progress: bool = False) -> None:
        """Start the dummy demo app with PostHog configuration."""
        # Set environment variables for PostHog integration
        # Start the Next.js app
        print(
            f"Starting the app at {self.product_app_path.absolute()} with API netloc {LOCAL_POSTHOG_NETLOC}, token {self.posthog_api_token}"
        )
        self._app_process = subprocess.Popen(
            ["node_modules/.bin/next", "dev", "--port", WEB_APP_NETLOC.split(":")[1]],
            cwd=self.product_app_path,
            env={
                **os.environ,
                "NEXT_PUBLIC_POSTHOG_API_HOST": f"http://{LOCAL_POSTHOG_NETLOC}",
                "NEXT_PUBLIC_POSTHOG_DEMO_TOKEN": self.posthog_api_token,
            },
            stdout=None if print_progress else subprocess.PIPE,
            stderr=None if print_progress else subprocess.PIPE,
        )

    async def _wait_for_netloc_ready(self, netloc: str) -> None:
        """Wait for the Hedgebox app to be ready."""
        async with aiohttp.ClientSession() as session:
            for _ in range(50):
                try:
                    # Timeout of 5 s as Next.js JIT builds can take a moment
                    async with session.get(f"http://{netloc}", timeout=ClientTimeout(total=5)) as response:
                        if response.ok:
                            return  # Good to go!
                except Exception as e:
                    print(f"Failed to connect to {netloc}: {e}")
                    pass
                await asyncio.sleep(0.5)
        raise RuntimeError(f"{netloc} failed to start")

    async def _stop_demo_app(self) -> None:
        """Stop the Hedgebox Next.js app."""
        if self._app_process:
            self._app_process.terminate()
            try:
                self._app_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._app_process.kill()
            self._app_process = None

    async def _replay_sessions(self, sessions: list[ReplayableSession], print_progress: bool) -> None:
        """Replay sessions using Playwright."""

        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=self.headless)

            try:
                for i, session in enumerate(sessions):
                    if print_progress:
                        print(f"Replaying session {i+1}/{len(sessions)}")
                    # Create new browser context for each session
                    context = await browser.new_context()
                    try:
                        await self._replay_single_session(context, session)
                    except:
                        raise
                    finally:
                        await context.close()
            except:
                raise
            finally:
                await browser.close()

    async def _replay_single_session(self, context, session: ReplayableSession) -> None:
        """Replay a single session with Playwright."""
        page = await context.new_page()

        try:
            # Calculate timing multiplier (compress long sessions)
            session_duration = (session.end_time - session.start_time).total_seconds()
            timing_multiplier = min(1.0, 300 / max(session_duration, 60))  # Max 5 minute replays

            for i, event in enumerate(session.events):
                # Calculate delay from previous event
                if i > 0:
                    delay_seconds = (event.timestamp - session.events[i - 1].timestamp).total_seconds()
                    compressed_delay = delay_seconds * timing_multiplier
                    await asyncio.sleep(min(compressed_delay, 10))  # Max 10 second delays

                # Replay the event
                await self._replay_event(page, event, session.person)
        except:
            raise
        finally:
            await page.close()

    async def _replay_event(self, page, event: SimEvent, person: HedgeboxPerson) -> None:
        """Replay a single event with Playwright."""
        if event.event == "$pageview":
            url = self._convert_url_to_localhost(event.properties.get("$current_url", ""))
            await page.goto(url)
            await page.wait_for_load_state("networkidle")

        elif event.event == EVENT_SIGNED_UP:
            await self._replay_signup(page, person)

        elif event.event == EVENT_LOGGED_IN:
            await self._replay_login(page, person)

        elif event.event == EVENT_UPLOADED_FILE:
            await self._replay_file_upload(page)

        elif event.event == EVENT_DOWNLOADED_FILE:
            await self._replay_file_download(page)

        elif event.event == EVENT_DELETED_FILE:
            await self._replay_file_delete(page)

        elif event.event == "$autocapture":
            await self._replay_click(page, event)

    def _convert_url_to_localhost(self, url: str) -> str:
        """Convert demo URLs to localhost."""
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url._replace(netloc=WEB_APP_NETLOC, scheme="http").geturl()

    async def _replay_signup(self, page, person: HedgeboxPerson) -> None:
        """Replay signup flow."""
        # Fill signup form
        await page.fill('input[type="email"]', person.email)
        await page.fill('input[name="name"]', person.name)
        await page.fill('input[type="password"]', "demo_password_123")

        # Submit form
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

    async def _replay_login(self, page, person: HedgeboxPerson) -> None:
        """Replay login flow."""
        # Fill login form
        await page.fill('input[type="email"]', person.email)
        await page.fill('input[type="password"]', "demo_password_123")

        # Submit form
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle", timeout=30000)

    async def _replay_file_upload(self, page) -> None:
        """Replay file upload action."""
        # Look for file upload button/input
        upload_selectors = ['input[type="file"]', 'button:has-text("Upload")', '[data-testid="upload-button"]']

        for selector in upload_selectors:
            try:
                if await page.is_visible(selector):
                    await page.click(selector)
                    break
            except:
                continue

    async def _replay_file_download(self, page) -> None:
        """Replay file download action."""
        # Look for download buttons
        download_selectors = ['button:has-text("Download")', '[data-testid="download-button"]', "a[download]"]

        for selector in download_selectors:
            try:
                if await page.is_visible(selector):
                    await page.click(selector)
                    break
            except:
                continue

    async def _replay_file_delete(self, page) -> None:
        """Replay file delete action."""
        # Look for delete buttons
        delete_selectors = [
            'button:has-text("Delete")',
            '[data-testid="delete-button"]',
            'button[aria-label*="delete"]',
        ]

        for selector in delete_selectors:
            try:
                if await page.is_visible(selector):
                    await page.click(selector)
                    # Handle confirmation dialog if it appears
                    try:
                        await page.click('button:has-text("Confirm")', timeout=2000)
                    except:
                        pass
                    break
            except:
                continue

    async def _replay_click(self, page, event: SimEvent) -> None:
        """Replay a click event."""
        # Try to find clickable element based on event properties
        element_selectors = []

        # Extract potential selectors from event
        if "$el_text" in event.properties:
            text = event.properties["$el_text"]
            element_selectors.append(f'button:has-text("{text}")')
            element_selectors.append(f'a:has-text("{text}")')

        # Try common interactive elements
        element_selectors.extend(["button:visible", "a:visible", '[role="button"]:visible'])

        for selector in element_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    # Click the first matching element
                    await elements[0].click()
                    break
            except:
                continue
