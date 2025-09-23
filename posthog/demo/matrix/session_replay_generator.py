import asyncio
import datetime as dt
import os
import random
import subprocess
import math
from pathlib import Path
from time import sleep
from typing import Optional
from dataclasses import dataclass
import urllib.parse
import requests

from posthog.demo.products.hedgebox.taxonomy import (
    EVENT_SIGNED_UP,
    EVENT_LOGGED_IN,
    EVENT_UPLOADED_FILE,
    EVENT_DOWNLOADED_FILE,
    EVENT_DELETED_FILE,
)

from playwright.async_api import Browser, async_playwright


@dataclass
class ReplayPerson:
    """Generic person data for session replay."""

    email: str
    name: str
    distinct_id: str


@dataclass
class ReplayEvent:
    """Generic event data for session replay."""

    event: str
    timestamp: dt.datetime
    properties: dict
    distinct_id: str


@dataclass
class ReplayableSession:
    """A session that can be replayed with Playwright."""

    person: ReplayPerson
    events: list[ReplayEvent]
    start_time: dt.datetime
    end_time: dt.datetime
    session_id: str


LOCAL_POSTHOG_NETLOC = "localhost:8010"
WEB_APP_NETLOC = "localhost:3000"


class SessionReplayGenerator:
    """Generates session recordings by replaying user behavior with Playwright."""

    app_path: Path
    posthog_api_token: str
    headless: bool
    _app_process: Optional[subprocess.Popen] = None

    def __init__(
        self,
        posthog_api_token: str,
        *,
        headless: bool = False,
    ):
        self.app_path = Path(__file__).parent.parent.parent / "demo" / "products" / "hedgebox" / "app"
        self.posthog_api_token = posthog_api_token
        self.headless = headless

    def generate_session_recordings(self, sessions: list[ReplayableSession], *, print_progress: bool = False) -> None:
        """Generate session replays for the given sessions."""
        if print_progress:
            print("Starting the demo app in the background...")
        self.start_demo_app(print_progress=print_progress)
        try:
            if print_progress:
                print("Waiting for the demo app to be ready...")
            self._wait_for_netloc_ready(WEB_APP_NETLOC)  # Next.js app should be ready by now
            self._wait_for_netloc_ready(LOCAL_POSTHOG_NETLOC)

            if print_progress:
                print("Beginning session replay automation...")
            asyncio.run(self._replay_sessions(sessions, print_progress))
        except:
            raise
        finally:
            self._stop_demo_app()
            if print_progress:
                print("Session replay generation completed")

    def start_demo_app(self, *, print_progress: bool = False) -> None:
        """Start the demo app with PostHog configuration."""
        # Set environment variables for PostHog integration
        # Start the Next.js app
        print(
            f"Starting the app at {self.app_path} with API netloc {LOCAL_POSTHOG_NETLOC}, token {self.posthog_api_token}"
        )
        self._app_process = subprocess.Popen(
            ["node_modules/.bin/next", "dev", "--port", WEB_APP_NETLOC.split(":")[1]],
            cwd=self.app_path,
            env={
                **os.environ,
                "NEXT_PUBLIC_POSTHOG_KEY": self.posthog_api_token,
            },
            stdout=None if print_progress else subprocess.PIPE,
            stderr=None if print_progress else subprocess.PIPE,
        )

    def _wait_for_netloc_ready(self, netloc: str) -> None:
        """Wait for the demo app to be ready."""
        for _ in range(50):
            try:
                # Timeout of 5 s as Next.js JIT builds can take a moment
                response = requests.get(f"http://{netloc}", timeout=5)
                if response.ok:
                    return  # Good to go!
            except Exception as e:
                print(f"Failed to connect to {netloc}: {e}")
                pass
            sleep(0.5)
        raise RuntimeError(f"{netloc} failed to start")

    def _stop_demo_app(self) -> None:
        """Stop the demo Next.js app."""
        if self._app_process:
            self._app_process.terminate()
            try:
                self._app_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._app_process.kill()
            self._app_process = None

    def cleanup_processes(self) -> None:
        """Emergency cleanup of any remaining processes."""
        if self._app_process:
            try:
                self._app_process.terminate()
                self._app_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._app_process.kill()
            except:
                pass
            self._app_process = None

    async def _replay_sessions(self, sessions: list[ReplayableSession], print_progress: bool) -> None:
        """Replay sessions using Playwright with proper timeout handling."""

        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(headless=self.headless)

                # Create tasks with individual timeouts
                tasks = []
                for session in sessions:
                    task = asyncio.create_task(
                        self._replay_single_session_with_timeout(browser, session, print_progress=print_progress)
                    )
                    tasks.append(task)

                # Wait for all tasks with overall timeout
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=600,  # 10 minutes max for all sessions
                    )
                except TimeoutError:
                    if print_progress:
                        print("Session replay timed out, cleaning up...")
                    # Cancel remaining tasks
                    for task in tasks:
                        if not task.done():
                            task.cancel()

            except Exception as e:
                if print_progress:
                    print(f"Error during session replay: {e}")
                raise
            finally:
                if browser:
                    try:
                        # Force close all contexts and browser
                        for context in browser.contexts:
                            try:
                                await asyncio.wait_for(context.close(), timeout=5)
                            except:
                                pass
                        await asyncio.wait_for(browser.close(), timeout=5)
                    except:
                        # Force kill browser process if needed
                        try:
                            browser._connection._transport.close()
                        except:
                            pass

    async def _replay_single_session_with_timeout(
        self, browser: Browser, session: ReplayableSession, *, print_progress: bool = False
    ) -> None:
        """Wrapper for single session replay with individual timeout."""
        try:
            # Individual session timeout (5 minutes max per session)
            await asyncio.wait_for(
                self._replay_single_session(browser, session, print_progress=print_progress), timeout=300
            )
        except TimeoutError:
            if print_progress:
                print(f"Session {session.session_id} timed out after 5 minutes")
            # Session timed out - context cleanup will happen in main method
        except Exception as e:
            if print_progress:
                print(f"Error replaying session {session.session_id}: {e}")
            # Other errors - let them propagate but don't crash everything

    async def _replay_single_session(
        self, browser: Browser, session: ReplayableSession, *, print_progress: bool = False
    ) -> None:
        """
        Replay a single session with Playwright using time control for compressed playback.

        This method uses Playwright's Clock API to simulate the passage of time, allowing us to:
        - Jump instantly between events that were originally minutes apart
        - Maintain accurate timestamps for PostHog analytics
        - Complete 10+ minute sessions in just a few seconds of real time
        - Add small realistic delays only for visual mouse movements
        """
        if print_progress:
            print(f"Replaying session {session.session_id}")
        # Create new browser context for each session
        context = None
        page = None
        try:
            context = await browser.new_context()
            page = await context.new_page()

            # Set up time control - start at the session's actual start time
            session_start_s = int(session.start_time.timestamp())
            await page.clock.install(time=session_start_s)
            await page.clock.pause_at(session_start_s)

            # Track session state for more realistic behavior
            session_state = {
                "first_pageview": True,
                "current_url": None,
                "is_authenticated": False,
                "mouse_x": random.randint(200, 800),
                "mouse_y": random.randint(200, 400),
                "viewport": {"width": 1280, "height": 720},
                "session_start_time": session.start_time,
            }

            # Start continuous mouse movement task
            mouse_task = asyncio.create_task(self._continuous_mouse_movement(page, session_state))

            try:
                current_time_s = session_start_s

                for i, event in enumerate(session.events):
                    # Jump to the event's timestamp instantly using Clock API
                    event_timestamp_s = int(event.timestamp.timestamp())

                    # Only fast-forward if we're moving forward in time
                    if event_timestamp_s > current_time_s:
                        time_diff_s = event_timestamp_s - current_time_s
                        await page.clock.fast_forward(time_diff_s)
                        current_time_s = event_timestamp_s

                    # Add a small realistic delay for mouse movements between events
                    if i > 0:
                        # Very short delay (0.5-2 seconds max) for realism
                        realistic_delay = min(2.0, random.uniform(0.5, 1.5))
                        await self._simulate_human_activity_during_delay(page, session_state, realistic_delay)

                    # Replay the event with session context
                    await self._replay_event(page, event, session.person, session_state)

                    # Update authentication state based on events
                    if event.event in [EVENT_SIGNED_UP, EVENT_LOGGED_IN]:
                        session_state["is_authenticated"] = True
            finally:
                # Cancel continuous mouse movement
                mouse_task.cancel()
                try:
                    await mouse_task
                except asyncio.CancelledError:
                    pass

            # Final timestamp jump to session end and allow PostHog to flush
            session_end_s = int(session.end_time.timestamp())
            current_page_time = await page.evaluate("Date.now()")
            if session_end_s > current_page_time:
                await page.clock.fast_forward(session_end_s - current_page_time)
            await asyncio.sleep(2)  # Brief real-time pause for PostHog flush
        except:
            raise
        finally:
            # Robust cleanup with timeouts
            if page:
                try:
                    await asyncio.wait_for(page.close(), timeout=10)
                except:
                    pass
            if context:
                try:
                    await asyncio.wait_for(context.close(), timeout=10)
                except:
                    pass

    async def _replay_event(self, page, event: ReplayEvent, person: ReplayPerson, session_state: dict) -> None:
        """Replay a single event with Playwright."""
        if event.event == "$pageview":
            url = self._convert_url_to_localhost(event.properties.get("$current_url", ""))

            if session_state["first_pageview"]:
                # First pageview: use goto as before
                await page.goto(url)
                await page.wait_for_load_state("networkidle")
                session_state["first_pageview"] = False
                session_state["current_url"] = url
                # Simulate initial page scanning after first load
                await self._simulate_page_arrival_behavior(page, session_state)
            else:
                # Subsequent pageviews: try to navigate naturally by clicking links
                if await self._navigate_by_clicking(page, url, session_state):
                    session_state["current_url"] = url
                    # Simulate scanning new page after navigation
                    await self._simulate_page_arrival_behavior(page, session_state)
                else:
                    # Fallback to goto if we can't find a way to navigate naturally
                    await page.goto(url)
                    await page.wait_for_load_state("networkidle")
                    session_state["current_url"] = url
                    await self._simulate_page_arrival_behavior(page, session_state)

        elif event.event == EVENT_SIGNED_UP:
            await self._replay_signup(page, person, session_state)

        elif event.event == EVENT_LOGGED_IN:
            await self._replay_login(page, person, session_state)

        elif event.event == EVENT_UPLOADED_FILE:
            await self._replay_file_upload(page, session_state)

        elif event.event == EVENT_DOWNLOADED_FILE:
            await self._replay_file_download(page, session_state)

        elif event.event == EVENT_DELETED_FILE:
            await self._replay_file_delete(page, session_state)

        elif event.event == "$autocapture":
            await self._replay_click(page, event, session_state)

    def _convert_url_to_localhost(self, url: str) -> str:
        """Convert demo URLs to localhost."""
        parsed_url = urllib.parse.urlparse(url)
        return parsed_url._replace(netloc=WEB_APP_NETLOC, scheme="http").geturl()

    async def _replay_signup(self, page, person: ReplayPerson, session_state: dict) -> None:
        """Replay signup flow with human-like behavior."""
        # Simulate reading the page before filling the form
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(1.0, 2.5))

        # Fill signup form with realistic typing delays
        await self._type_naturally_with_mouse(page, 'input[type="email"]', person.email, session_state)
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.5, 1.0))

        await self._type_naturally_with_mouse(page, 'input[name="name"]', person.name, session_state)
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.5, 1.0))

        await self._type_naturally_with_mouse(page, 'input[type="password"]', "demo_password_123", session_state)
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.8, 1.5))

        # Submit form with mouse movement
        try:
            submit_button = await page.wait_for_selector('button[type="submit"]', timeout=2000)
            if submit_button:
                await self._move_mouse_to_element_and_click(page, submit_button, session_state)
        except:
            # Fallback to regular click
            await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

    async def _replay_login(self, page, person: ReplayPerson, session_state: dict) -> None:
        """Replay login flow with human-like behavior."""
        # Simulate reading the page before filling the form
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.8, 1.5))

        # Fill login form with realistic typing delays
        await self._type_naturally_with_mouse(page, 'input[type="email"]', person.email, session_state)
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.3, 0.8))

        await self._type_naturally_with_mouse(page, 'input[type="password"]', "demo_password_123", session_state)
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.5, 1.0))

        # Submit form with mouse movement
        try:
            submit_button = await page.wait_for_selector('button[type="submit"]', timeout=2000)
            if submit_button:
                await self._move_mouse_to_element_and_click(page, submit_button, session_state)
        except:
            # Fallback to regular click
            await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle", timeout=30000)

    async def _replay_file_upload(self, page, session_state: dict) -> None:
        """Replay file upload action with human-like behavior."""
        # Simulate looking for upload option with mouse activity
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.5, 1.2))

        # Look for file upload button/input
        upload_selectors = ['input[type="file"]', 'button:has-text("Upload")', '[data-testid="upload-button"]']

        for selector in upload_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=1000)
                if element and await element.is_visible():
                    await self._move_mouse_to_element_and_click(page, element, session_state)
                    # Wait after action with mouse activity
                    await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.5, 1.0))
                    break
            except:
                continue

    async def _replay_file_download(self, page, session_state: dict) -> None:
        """Replay file download action with human-like behavior."""
        # Simulate looking for download option with mouse activity
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.4, 1.0))

        # Look for download buttons
        download_selectors = ['button:has-text("Download")', '[data-testid="download-button"]', "a[download]"]

        for selector in download_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=1000)
                if element and await element.is_visible():
                    await self._move_mouse_to_element_and_click(page, element, session_state)
                    # Wait after action with mouse activity
                    await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.3, 0.8))
                    break
            except:
                continue

    async def _replay_file_delete(self, page, session_state: dict) -> None:
        """Replay file delete action with human-like behavior."""
        # Simulate looking for delete option with mouse activity
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.5, 1.0))

        # Look for delete buttons
        delete_selectors = [
            'button:has-text("Delete")',
            '[data-testid="delete-button"]',
            'button[aria-label*="delete"]',
        ]

        for selector in delete_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=1000)
                if element and await element.is_visible():
                    # Pause before clicking (humans hesitate before deleting) with mouse activity
                    await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.8, 1.5))
                    await self._move_mouse_to_element_and_click(page, element, session_state)

                    # Handle confirmation dialog if it appears
                    try:
                        confirm_button = await page.wait_for_selector('button:has-text("Confirm")', timeout=2000)
                        if confirm_button:
                            # Slight pause before confirming (reading the dialog) with mouse activity
                            await self._simulate_human_activity_during_delay(
                                page, session_state, random.uniform(0.5, 1.2)
                            )
                            await self._move_mouse_to_element_and_click(page, confirm_button, session_state)
                            # Wait after confirming
                            await self._simulate_human_activity_during_delay(
                                page, session_state, random.uniform(0.3, 0.8)
                            )
                    except:
                        pass
                    break
            except:
                continue

    async def _replay_click(self, page, event: ReplayEvent, session_state: dict) -> None:
        """Replay a click event with human-like behavior."""
        # Simulate looking for the element with mouse activity
        await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.2, 0.6))

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
                    target_element = elements[0]

                    # Simulate reading/considering the element before clicking
                    await self._hover_and_read_element(
                        page, target_element, session_state, duration=random.uniform(0.3, 0.8)
                    )

                    # Brief hesitation before clicking (decision making)
                    await asyncio.sleep(random.uniform(0.1, 0.3))

                    # Move mouse to element and click
                    await self._move_mouse_to_element_and_click(page, target_element, session_state)

                    # Small pause after clicking with mouse activity
                    await self._simulate_human_activity_during_delay(page, session_state, random.uniform(0.2, 0.5))
                    break
            except:
                continue

    async def _continuous_mouse_movement(self, page, session_state: dict) -> None:
        """Continuous background mouse movement task that runs throughout the session."""
        try:
            while True:
                await asyncio.sleep(random.uniform(0.1, 0.5))

                # Occasionally do small random movements (fidgeting)
                if random.random() < 0.3:
                    await self._small_mouse_fidget(page, session_state)

                # Sometimes do exploratory movements
                if random.random() < 0.1:
                    await self._exploratory_mouse_movement(page, session_state)

        except asyncio.CancelledError:
            raise
        except:
            # Continue if any mouse movement fails
            pass

    async def _simulate_page_arrival_behavior(self, page, session_state: dict) -> None:
        """Simulate realistic behavior when arriving at a new page."""
        try:
            current_url = session_state.get("current_url", "")

            # Different scanning patterns based on page type
            if "/files" in current_url and not any(x in current_url for x in ["/files/file", "/files/shared"]):
                # Files list page - simulate systematic file browsing
                await self._simulate_file_list_scanning(page, session_state)
            elif "/files/file" in current_url:
                # Individual file page - simulate reading file details
                await self._simulate_file_detail_reading(page, session_state)
            elif "/pricing" in current_url:
                # Pricing page - simulate comparing plans
                await self._simulate_pricing_comparison(page, session_state)
            else:
                # Generic page - simulate general page scanning
                await self._simulate_general_page_scanning(page, session_state)

        except:
            # Fallback to basic scanning if anything fails
            await self._simulate_general_page_scanning(page, session_state)

    async def _simulate_file_list_scanning(self, page, session_state: dict) -> None:
        """Simulate realistic file browsing behavior - scanning through files methodically."""
        try:
            # First, look at the page header/stats
            await self._look_at_page_section(page, session_state, "header", duration=random.uniform(0.8, 1.2))

            # Check storage usage stats
            stats_selectors = [".stats", ".stat", '[class*="storage"]']
            for selector in stats_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=500)
                    if element and await element.is_visible():
                        await self._hover_and_read_element(
                            page, element, session_state, duration=random.uniform(0.6, 1.0)
                        )
                        break
                except:
                    continue

            # Scan through files systematically (not randomly)
            file_selectors = [
                ".card",  # Grid view cards
                'tr:has(input[type="checkbox"])',  # Table rows
                '[class*="file"]',  # Any file containers
            ]

            for selector in file_selectors:
                try:
                    file_elements = await page.query_selector_all(selector)
                    if file_elements and len(file_elements) > 0:
                        # Scan through first few files methodically
                        scan_count = min(len(file_elements), random.randint(3, 6))

                        for i in range(scan_count):
                            element = file_elements[i]
                            if await element.is_visible():
                                # Simulate reading file name and details
                                await self._hover_and_read_element(
                                    page, element, session_state, duration=random.uniform(0.8, 1.5)
                                )

                                # Brief pause between files (decision making)
                                await asyncio.sleep(random.uniform(0.2, 0.4))
                        break
                except:
                    continue

        except:
            pass

    async def _simulate_file_detail_reading(self, page, session_state: dict) -> None:
        """Simulate reading file details on individual file pages."""
        try:
            # Read breadcrumb to understand context
            await self._look_at_page_section(page, session_state, ".breadcrumbs", duration=random.uniform(0.4, 0.7))

            # Focus on file header/title
            title_selectors = ["h1", ".file-name", '[class*="title"]']
            for selector in title_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=500)
                    if element and await element.is_visible():
                        await self._hover_and_read_element(
                            page, element, session_state, duration=random.uniform(1.0, 1.5)
                        )
                        break
                except:
                    continue

            # Scan file metadata
            metadata_selectors = [".stat", ".badge", '[class*="meta"]', '[class*="detail"]']
            for selector in metadata_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements[:3]:  # Don't scan too many
                        if await element.is_visible():
                            await self._hover_and_read_element(
                                page, element, session_state, duration=random.uniform(0.5, 0.8)
                            )
                            await asyncio.sleep(random.uniform(0.1, 0.3))
                except:
                    continue

        except:
            pass

    async def _simulate_pricing_comparison(self, page, session_state: dict) -> None:
        """Simulate comparing pricing plans."""
        try:
            # Look at page title first
            await self._look_at_page_section(page, session_state, "h1", duration=random.uniform(0.6, 1.0))

            # Scan through pricing cards systematically
            plan_selectors = [".card", '[class*="plan"]', '[class*="pricing"]']
            for selector in plan_selectors:
                try:
                    plan_elements = await page.query_selector_all(selector)
                    if plan_elements and len(plan_elements) > 1:
                        # Compare plans by looking at each one
                        for i, element in enumerate(plan_elements[:4]):  # Max 4 plans
                            if await element.is_visible():
                                # Longer reading time for pricing (decision making)
                                await self._hover_and_read_element(
                                    page, element, session_state, duration=random.uniform(1.2, 2.0)
                                )

                                # Pause between plans (comparison thinking)
                                if i < len(plan_elements) - 1:
                                    await asyncio.sleep(random.uniform(0.4, 0.8))
                        break
                except:
                    continue

        except:
            pass

    async def _simulate_general_page_scanning(self, page, session_state: dict) -> None:
        """Generic page scanning behavior - F-pattern reading."""
        try:
            # Look at top of page first (header area)
            await self._look_at_page_section(page, session_state, "header", duration=random.uniform(0.5, 0.8))

            # Scan main content area in F-pattern
            content_selectors = ["main", ".container", ".content", "body"]
            for selector in content_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=500)
                    if element and await element.is_visible():
                        await self._f_pattern_scan(page, element, session_state)
                        break
                except:
                    continue

        except:
            pass

    async def _hover_and_read_element(self, page, element, session_state: dict, duration: float = 1.0) -> None:
        """Move mouse to element and simulate reading it."""
        try:
            box = await element.bounding_box()
            if box:
                # Move to element
                target_x = box["x"] + box["width"] / 2 + random.randint(-10, 10)
                target_y = box["y"] + box["height"] / 2 + random.randint(-5, 5)
                await self._smooth_mouse_move(page, session_state, target_x, target_y, speed="medium")

                # Stay and "read" the element
                await asyncio.sleep(duration)

                # Small fidget while reading
                if random.random() < 0.3:
                    await self._small_mouse_fidget(page, session_state)
        except:
            pass

    async def _look_at_page_section(self, page, session_state: dict, selector: str, duration: float = 0.8) -> None:
        """Look at a specific page section."""
        try:
            element = await page.wait_for_selector(selector, timeout=500)
            if element and await element.is_visible():
                await self._hover_and_read_element(page, element, session_state, duration)
        except:
            pass

    async def _f_pattern_scan(self, page, container_element, session_state: dict) -> None:
        """Simulate F-pattern reading behavior."""
        try:
            box = await container_element.bounding_box()
            if not box:
                return

            # F-pattern: horizontal scan at top, shorter horizontal scan in middle, vertical scan on left

            # Top horizontal scan
            start_x = box["x"] + 50
            end_x = box["x"] + box["width"] - 50
            top_y = box["y"] + 100

            await self._smooth_mouse_move(page, session_state, start_x, top_y, speed="slow")
            await asyncio.sleep(random.uniform(0.3, 0.6))
            await self._smooth_mouse_move(page, session_state, end_x, top_y, speed="slow")

            # Middle horizontal scan (shorter)
            middle_y = box["y"] + box["height"] / 2
            middle_end_x = box["x"] + box["width"] * 0.6

            await self._smooth_mouse_move(page, session_state, start_x, middle_y, speed="medium")
            await asyncio.sleep(random.uniform(0.2, 0.4))
            await self._smooth_mouse_move(page, session_state, middle_end_x, middle_y, speed="slow")

            # Vertical scan down the left side
            bottom_y = box["y"] + box["height"] - 100
            await self._smooth_mouse_move(page, session_state, start_x, bottom_y, speed="slow")

        except:
            pass

    async def _simulate_human_activity_during_delay(self, page, session_state: dict, delay_seconds: float) -> None:
        """Simulate realistic human mouse activity during delays between events."""
        if delay_seconds <= 0:
            return

        # Cap the delay at 10 seconds max
        delay_seconds = min(delay_seconds, 10)

        # Break delay into smaller chunks with mouse activity
        chunks = max(1, int(delay_seconds / 0.5))  # 500ms chunks
        chunk_delay = delay_seconds / chunks

        for _ in range(chunks):
            activity_type = random.choices(
                ["fidget", "explore", "scan", "hover", "scroll", "pause"], weights=[30, 15, 20, 10, 15, 10]
            )[0]

            if activity_type == "fidget":
                await self._small_mouse_fidget(page, session_state)
            elif activity_type == "explore":
                await self._exploratory_mouse_movement(page, session_state)
            elif activity_type == "scan":
                await self._scanning_mouse_movement(page, session_state)
            elif activity_type == "hover":
                await self._hover_over_elements(page, session_state)
            elif activity_type == "scroll":
                await self._random_scroll_behavior(page, session_state)
            # 'pause' means no mouse movement - human is thinking/reading

            await asyncio.sleep(chunk_delay)

    async def _small_mouse_fidget(self, page, session_state: dict) -> None:
        """Small random mouse movements - typical human fidgeting."""
        try:
            current_x = session_state["mouse_x"]
            current_y = session_state["mouse_y"]

            # Small random movements (5-25 pixels)
            dx = random.randint(-25, 25)
            dy = random.randint(-25, 25)

            new_x = max(50, min(session_state["viewport"]["width"] - 50, current_x + dx))
            new_y = max(50, min(session_state["viewport"]["height"] - 50, current_y + dy))

            await self._smooth_mouse_move(page, session_state, new_x, new_y, speed="fast")

        except:
            pass

    async def _exploratory_mouse_movement(self, page, session_state: dict) -> None:
        """Larger exploratory movements - user exploring the page."""
        try:
            # Pick a random area of the page to explore
            viewport = session_state["viewport"]

            # Define interesting areas (header, main content, sidebar, footer)
            areas = [
                {"x_range": (100, viewport["width"] - 100), "y_range": (50, 150)},  # Header
                {"x_range": (100, viewport["width"] - 100), "y_range": (150, 500)},  # Main content
                {"x_range": (100, viewport["width"] - 100), "y_range": (500, 600)},  # Lower content
            ]

            area = random.choice(areas)
            target_x = random.randint(*area["x_range"])
            target_y = random.randint(*area["y_range"])

            await self._smooth_mouse_move(page, session_state, target_x, target_y, speed="medium")

        except:
            pass

    async def _scanning_mouse_movement(self, page, session_state: dict) -> None:
        """Mouse following text/content - reading behavior."""
        try:
            current_x = session_state["mouse_x"]
            current_y = session_state["mouse_y"]

            # Simulate reading left-to-right, top-to-bottom movements
            if random.random() < 0.7:  # Horizontal scanning (reading)
                direction = 1 if random.random() < 0.8 else -1  # Mostly left-to-right
                distance = random.randint(50, 200)
                new_x = max(100, min(session_state["viewport"]["width"] - 100, current_x + direction * distance))
                new_y = current_y + random.randint(-10, 10)  # Slight vertical drift
            else:  # Vertical movement (scrolling with eyes)
                direction = 1 if random.random() < 0.6 else -1  # Mostly downward
                distance = random.randint(30, 100)
                new_x = current_x + random.randint(-20, 20)  # Slight horizontal drift
                new_y = max(100, min(session_state["viewport"]["height"] - 100, current_y + direction * distance))

            await self._smooth_mouse_move(page, session_state, new_x, new_y, speed="slow")

        except:
            pass

    async def _hover_over_elements(self, page, session_state: dict) -> None:
        """Hover over interactive elements - goal-oriented behavior."""
        try:
            # Try to find interactive elements to hover over
            selectors = [
                "button:visible",
                "a:visible",
                "input:visible",
                '[role="button"]:visible',
                ".btn:visible",
                "nav a:visible",
            ]

            for selector in selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        # Pick a random element
                        element = random.choice(elements[:5])  # Don't consider too many

                        # Get element position
                        box = await element.bounding_box()
                        if box:
                            # Move to element with some randomness
                            target_x = box["x"] + box["width"] / 2 + random.randint(-10, 10)
                            target_y = box["y"] + box["height"] / 2 + random.randint(-5, 5)

                            await self._smooth_mouse_move(page, session_state, target_x, target_y, speed="medium")

                            # Hover for a moment
                            await asyncio.sleep(random.uniform(0.2, 0.8))
                            return
                except:
                    continue
        except:
            pass

    async def _random_scroll_behavior(self, page, session_state: dict) -> None:
        """Random scrolling behavior."""
        try:
            # Scroll up or down
            direction = random.choice([-1, 1])
            scroll_amount = random.randint(100, 300) * direction

            # Move mouse to a scrollable area first
            scroll_x = random.randint(200, session_state["viewport"]["width"] - 200)
            scroll_y = random.randint(200, session_state["viewport"]["height"] - 200)

            await self._smooth_mouse_move(page, session_state, scroll_x, scroll_y, speed="fast")

            # Perform scroll
            await page.mouse.wheel(0, scroll_amount)

        except:
            pass

    async def _smooth_mouse_move(
        self, page, session_state: dict, target_x: float, target_y: float, speed: str = "medium"
    ) -> None:
        """Move mouse smoothly from current position to target with human-like curves."""
        try:
            start_x = session_state["mouse_x"]
            start_y = session_state["mouse_y"]

            # Don't move if we're already very close
            distance = math.sqrt((target_x - start_x) ** 2 + (target_y - start_y) ** 2)
            if distance < 5:
                return

            # Speed settings
            speed_settings = {
                "slow": {"steps": max(8, int(distance / 15)), "base_delay": 0.05},
                "medium": {"steps": max(5, int(distance / 25)), "base_delay": 0.03},
                "fast": {"steps": max(3, int(distance / 40)), "base_delay": 0.02},
            }

            settings = speed_settings.get(speed, speed_settings["medium"])
            steps = settings["steps"]
            base_delay = settings["base_delay"]

            # Generate bezier curve for natural movement
            control_x = start_x + (target_x - start_x) * 0.5 + random.randint(-50, 50)
            control_y = start_y + (target_y - start_y) * 0.5 + random.randint(-30, 30)

            for i in range(steps + 1):
                t = i / steps

                # Bezier curve calculation
                x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x
                y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y

                # Add small random variations
                x += random.uniform(-2, 2)
                y += random.uniform(-2, 2)

                # Ensure we stay within bounds
                x = max(10, min(session_state["viewport"]["width"] - 10, x))
                y = max(10, min(session_state["viewport"]["height"] - 10, y))

                await page.mouse.move(x, y)
                session_state["mouse_x"] = x
                session_state["mouse_y"] = y

                # Variable delay - faster in middle, slower at start/end
                delay_multiplier = 1.0 + 0.5 * math.sin(t * math.pi)  # Slower at ends
                await asyncio.sleep(base_delay * delay_multiplier + random.uniform(0, 0.01))

        except:
            pass

    async def _simulate_navigation_search_behavior(self, page, session_state: dict, target_path: str) -> None:
        """Simulate looking for navigation elements before clicking."""
        try:
            # Look at the header/navigation area first
            nav_selectors = ["header", "nav", ".navbar", '[role="navigation"]']
            for selector in nav_selectors:
                try:
                    nav_element = await page.wait_for_selector(selector, timeout=500)
                    if nav_element and await nav_element.is_visible():
                        # Scan the navigation area
                        await self._hover_and_read_element(
                            page, nav_element, session_state, duration=random.uniform(0.4, 0.8)
                        )

                        # Look at individual nav links
                        nav_links = await nav_element.query_selector_all("a")
                        scan_count = min(len(nav_links), random.randint(2, 4))

                        for i in range(scan_count):
                            if nav_links[i] and await nav_links[i].is_visible():
                                await self._hover_and_read_element(
                                    page, nav_links[i], session_state, duration=random.uniform(0.2, 0.5)
                                )
                                # Brief pause between nav items
                                await asyncio.sleep(random.uniform(0.1, 0.2))
                        break
                except:
                    continue

            # If looking for files, might check main content area too
            if "files" in target_path:
                try:
                    # Look for "Go to files" buttons or file-related links in main content
                    content_selectors = ["main", ".container", ".content"]
                    for selector in content_selectors:
                        content_element = await page.wait_for_selector(selector, timeout=300)
                        if content_element and await content_element.is_visible():
                            # Quick scan of main content for file-related links
                            file_links = await content_element.query_selector_all(
                                'a:has-text("file"), button:has-text("file")'
                            )
                            if file_links:
                                # Look at the first file-related link found
                                await self._hover_and_read_element(
                                    page, file_links[0], session_state, duration=random.uniform(0.3, 0.6)
                                )
                            break
                except:
                    pass

        except:
            pass

    async def _navigate_by_clicking(self, page, target_url: str, session_state: dict) -> bool:
        """Attempt to navigate to target URL by clicking appropriate links with realistic behavior."""
        try:
            # Parse target URL to get the path
            from urllib.parse import urlparse

            target_path = urlparse(target_url).path

            # Map of paths to likely link selectors based on our analysis of the Hedgebox app
            navigation_map = {
                "/": ['a[href="/"]', 'a:has-text("Hedgebox")', 'a:has-text("Home")'],
                "/signup": [
                    'a[href="/signup"]',
                    'button:has-text("Sign up")',
                    'a:has-text("Get started")',
                    'a:has-text("Start your journey")',
                ],
                "/login": ['a[href="/login"]', 'a:has-text("Log in")', 'button:has-text("Log in")'],
                "/pricing": ['a[href="/pricing"]', 'a:has-text("Pricing")', 'a:has-text("View pricing")'],
                "/mariustechtips": ['a[href="/mariustechtips"]', 'a:has-text("Blog")'],
                "/files": ['a[href="/files"]', 'a:has-text("Files")', 'a:has-text("Go to files")'],
                "/account/settings": [
                    'a[href="/account/settings"]',
                    'a:has-text("Account Settings")',
                    'a:has-text("Account settings")',
                ],
                "/account/billing": ['a[href="/account/billing"]', 'a:has-text("Billing")'],
                "/account/team": ['a[href="/account/team"]', 'a:has-text("Team")'],
            }

            selectors = navigation_map.get(target_path, [])

            # Add some generic selectors that might work
            selectors.extend(
                [f'a[href="{target_path}"]', f'a[href*="{target_path}"]', f'a:has-text("{target_path.split("/")[-1]}")']
            )

            # Simulate looking for the navigation element first
            await self._simulate_navigation_search_behavior(page, session_state, target_path)

            # Try each selector until one works
            for selector in selectors:
                try:
                    # Wait briefly to see if element is available
                    element = await page.wait_for_selector(selector, timeout=1000)
                    if element and await element.is_visible():
                        # Simulate considering this link before clicking
                        await self._hover_and_read_element(
                            page, element, session_state, duration=random.uniform(0.3, 0.8)
                        )

                        # Move mouse to element and click with realistic behavior
                        await self._move_mouse_to_element_and_click(page, element, session_state)
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        return True
                except:
                    continue

            # If we're on a page with a dropdown menu (authenticated user), try opening it first
            if session_state.get("is_authenticated") and target_path.startswith("/account/"):
                try:
                    # Try to open user profile dropdown
                    dropdown_selectors = [
                        '.dropdown-end [role="button"]',
                        'button[data-testid="user-menu"]',
                        ".avatar",
                        '[data-dropdown="profile"]',
                    ]

                    for dropdown_selector in dropdown_selectors:
                        try:
                            dropdown = await page.wait_for_selector(dropdown_selector, timeout=1000)
                            if dropdown and await dropdown.is_visible():
                                await self._move_mouse_to_element_and_click(page, dropdown, session_state)
                                await asyncio.sleep(0.5)  # Wait for dropdown to open

                                # Now try the original selectors again
                                for selector in selectors:
                                    try:
                                        element = await page.wait_for_selector(selector, timeout=1000)
                                        if element and await element.is_visible():
                                            await self._move_mouse_to_element_and_click(page, element, session_state)
                                            await page.wait_for_load_state("networkidle", timeout=10000)
                                            return True
                                    except:
                                        continue
                                break
                        except:
                            continue
                except:
                    pass

            return False
        except:
            return False

    async def _type_naturally(self, page, selector: str, text: str) -> None:
        """Type text with human-like speed and behavior."""
        try:
            element = await page.wait_for_selector(selector, timeout=2000)
            if element:
                # Clear the field first
                await element.click()
                await page.keyboard.press("Meta+a")  # Select all
                await asyncio.sleep(0.1)

                # Type each character with slight random delays
                for char in text:
                    await page.keyboard.type(char)
                    # Random delay between characters (30-120ms)
                    await asyncio.sleep(random.uniform(0.03, 0.12))

                # Small pause after typing
                await asyncio.sleep(random.uniform(0.2, 0.5))
        except:
            # Fallback to regular fill if natural typing fails
            try:
                await page.fill(selector, text)
            except:
                pass

    async def _move_mouse_to_element_and_click(self, page, element, session_state: dict) -> None:
        """Move mouse to element in a human-like way, then click."""
        try:
            # Get element position
            box = await element.bounding_box()
            if box:
                # Calculate target position with some randomness
                target_x = box["x"] + box["width"] / 2 + random.randint(-int(box["width"] / 4), int(box["width"] / 4))
                target_y = (
                    box["y"] + box["height"] / 2 + random.randint(-int(box["height"] / 4), int(box["height"] / 4))
                )

                # Move mouse to element
                await self._smooth_mouse_move(page, session_state, target_x, target_y, speed="medium")

                # Small pause before clicking (human hesitation)
                await asyncio.sleep(random.uniform(0.1, 0.3))

                # Click the element
                await element.click()

                # Small pause after clicking
                await asyncio.sleep(random.uniform(0.1, 0.2))
        except:
            # Fallback to regular click
            try:
                await element.click()
            except:
                pass

    async def _type_naturally_with_mouse(self, page, selector: str, text: str, session_state: dict) -> None:
        """Type text with natural mouse movement to the input field first."""
        try:
            element = await page.wait_for_selector(selector, timeout=2000)
            if element:
                # Move mouse to input field before typing
                await self._move_mouse_to_element_and_click(page, element, session_state)

                # Clear the field
                await page.keyboard.press("Meta+a")  # Select all
                await asyncio.sleep(0.1)

                # Type each character with slight random delays
                for char in text:
                    await page.keyboard.type(char)
                    # Random delay between characters (30-120ms)
                    await asyncio.sleep(random.uniform(0.03, 0.12))

                    # Occasionally move mouse slightly while typing (fidgeting)
                    if random.random() < 0.1:
                        current_x = session_state.get("mouse_x", 640)
                        current_y = session_state.get("mouse_y", 360)
                        fidget_x = current_x + random.randint(-5, 5)
                        fidget_y = current_y + random.randint(-3, 3)
                        await page.mouse.move(fidget_x, fidget_y)
                        session_state["mouse_x"] = fidget_x
                        session_state["mouse_y"] = fidget_y

                # Small pause after typing
                await asyncio.sleep(random.uniform(0.2, 0.5))
        except:
            # Fallback to regular typing
            try:
                await page.fill(selector, text)
            except:
                pass
