"""
Python agent loop. Replaces the Node/Stagehand runner.

Drives a Browserbase cloud Chrome over CDP with sync Playwright. Each step we
re-enumerate the page's visible interactive elements via a JS evaluate, attach
a stable `data-agentic-ref="N"` attribute to each one, and hand the LLM a
compact list. The LLM acts by `ref` (e.g. `click(ref=3)`); we resolve the
locator with `page.locator('[data-agentic-ref="N"]')` and act on the actual
element. No label-guessing in Python, no string-similarity matching — the
LLM sees what's really on the page and points at exactly one thing.

We use PostHog's internal LLM Gateway (OpenAI-compatible interface) so no
personal Anthropic key is needed.

The loop yields an `AgentEvent` stream so the caller can either:
- iterate to the end and persist the final state (see execution.execute_agentic_test)
- forward each event as Server-Sent Events for a live progress UI

Final event is always type="final" carrying the runner contract that
`execution.execute_agentic_test` expects:

    { passed, output, error?, external_session_id, screenshot_url }
"""

import json
import time
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from playwright.sync_api import BrowserContext, Page, sync_playwright

from posthog.llm.gateway_client import get_llm_client

from .browserbase import DEFAULT_REGION, SUPPORTED_REGIONS, BrowserbaseSession, open_session

logger = structlog.get_logger(__name__)

MODEL = "claude-sonnet-4-6"
LLM_PRODUCT = "agentic_tests"
MAX_OUTPUT_TOKENS = 1024
PAGE_SETTLE_MS = 800
# Wait this long after we eagerly pair with posthog-js so rrweb has time to take its
# first full DOM snapshot of the current page. Without this, the recording can start
# from the *next* page the agent navigates to (the recorder is torn down on the hard
# nav before it ever flushes the previous page's snapshot).
POSTHOG_RECORDER_WARMUP_MS = 1500
ACTION_TIMEOUT_MS = 5000
MAX_REFS_PER_SNAPSHOT = 60  # keep token usage bounded; rare to need more
_SNAPSHOT_MARKER = "\n\nUpdated page state:\n"


EventType = Literal["status", "tool_call", "tool_result", "model_text", "final"]


@dataclass
class AgentEvent:
    type: EventType
    data: dict[str, Any]
    step: int = 0


@dataclass
class _RunState:
    step: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOLS: list[dict[str, Any]] = [
    _fn("goto", "Navigate to a URL.", {"url": {"type": "string"}}, ["url"]),
    _fn(
        "click",
        "Click an interactive element by its `ref` number from the page snapshot.",
        {"ref": {"type": "integer"}},
        ["ref"],
    ),
    _fn(
        "fill",
        "Type a string into an input by its `ref` number. Replaces existing content. Use this for every text-entry — never `press` one character at a time.",
        {"ref": {"type": "integer"}, "value": {"type": "string"}},
        ["ref", "value"],
    ),
    _fn(
        "press",
        "Press a single keyboard key (e.g. 'Enter', 'Tab', 'Escape'). Do NOT use this to type words.",
        {"key": {"type": "string"}},
        ["key"],
    ),
    _fn(
        "wait",
        "Pause briefly to let the page settle. Use sparingly.",
        {"ms": {"type": "integer", "minimum": 100, "maximum": 5000}},
        ["ms"],
    ),
    _fn(
        "done",
        "Finish the test with a pass/fail verdict and a one-sentence reason.",
        {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
        ["passed", "reason"],
    ),
]


SYSTEM_PROMPT = """You are an automated UI test agent. You will be given a natural-language test
prompt and the current state of a web page, formatted as a numbered list of interactive
elements. Each line shows `[ref] role name="..." type="..." value="..."`. Drive the
browser using the provided tools to complete the task, then call `done` with your
pass/fail verdict.

Rules:
- One tool call per turn. Inspect the resulting page state before deciding the next action.
- Refer to elements by their `ref` number. Re-read the snapshot after each action — refs
  are re-assigned per step, so what was `[3]` may not be `[3]` next turn.
- For text entry: ALWAYS use `fill`. Never type words one character at a time with `press`.
- If you need to register, invent realistic data (name, email like
  llm-test+<random>@example.com, password ≥ 12 chars).
- If the page state shows the task is satisfied, call `done(passed=true, ...)`.
- If you get stuck (same screen for 3+ turns, or repeated tool errors), call
  `done(passed=false, ...)` with the reason.
- Common interstitials (ngrok warning, cookie banners) — click through them first."""


# JS to enumerate visible interactive elements and tag each with data-agentic-ref.
# Runs in the page once per snapshot. Returns a list of dicts the runner formats.
_ENUMERATE_JS = """
() => {
    const SELECTOR = [
        'button', '[role=button]',
        'a[href]', '[role=link]',
        'input:not([type=hidden])', 'textarea', 'select',
        '[role=textbox]', '[role=combobox]', '[role=searchbox]',
        '[role=checkbox]', '[role=radio]', '[role=switch]',
        '[role=tab]', '[role=menuitem]', '[role=option]',
        '[contenteditable=true]',
    ].join(', ');

    // Clear prior annotations so refs don't accumulate across snapshots.
    document.querySelectorAll('[data-agentic-ref]').forEach(el => el.removeAttribute('data-agentic-ref'));

    const isVisible = (el) => {
        if (!el.isConnected) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return false;
        return true;
    };

    const elements = Array.from(document.querySelectorAll(SELECTOR)).filter(isVisible);
    const out = [];
    for (let i = 0; i < elements.length && out.length < %MAX_REFS%; i++) {
        const el = elements[i];
        const ref = out.length + 1;
        el.setAttribute('data-agentic-ref', String(ref));
        const rawName =
            el.getAttribute('aria-label')
            || el.getAttribute('placeholder')
            || el.getAttribute('alt')
            || (el.innerText || el.textContent || '').trim()
            || el.getAttribute('value')
            || '';
        out.push({
            ref,
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || null,
            name: rawName.slice(0, 100),
            type: el.getAttribute('type') || null,
            value: (el.value || '').slice(0, 60),
            disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
        });
    }
    return { url: location.href, title: document.title, elements: out };
}
""".replace("%MAX_REFS%", str(MAX_REFS_PER_SNAPSHOT))


def _enumerate(page: Page) -> tuple[dict[int, Any], str]:
    """Tag DOM with refs and return (refs map, rendered snapshot string)."""
    try:
        data = page.evaluate(_ENUMERATE_JS) or {}
    except Exception as exc:  # noqa: BLE001 — surface as empty snapshot
        return {}, f"URL: {page.url}\nTitle: (snapshot error: {exc})\n\nInteractive elements:\n(none)"

    refs: dict[int, Any] = {}
    lines: list[str] = []
    for item in data.get("elements", []):
        ref = int(item["ref"])
        refs[ref] = page.locator(f'[data-agentic-ref="{ref}"]')
        role = item.get("role") or item.get("tag")
        parts = [f"[{ref}] {role}"]
        name = (item.get("name") or "").strip()
        if name:
            parts.append(f"name={name!r}")
        typ = item.get("type")
        if typ:
            parts.append(f"type={typ}")
        val = (item.get("value") or "").strip()
        if val:
            parts.append(f"value={val!r}")
        if item.get("disabled"):
            parts.append("disabled")
        lines.append(" ".join(parts))

    rendered = (
        f"URL: {data.get('url') or page.url}\n"
        f"Title: {data.get('title') or ''}\n\n"
        f"Interactive elements ({len(refs)}):\n" + ("\n".join(lines) if lines else "(none)")
    )
    return refs, rendered


def run_agent(
    *,
    prompt: str,
    target_url: str,
    max_steps: int = 20,
    regions: list[str] | None = None,
    test_id: str = "",
    test_name: str = "",
    run_id: str = "",
) -> Iterator[AgentEvent]:
    """Run a single agentic test, yielding events as work happens.

    `regions`: list of Browserbase region codes the test may pick from (one chosen at random
    per run). Empty/None -> Browserbase default.
    `test_id`, `run_id`, `test_name`: surfaced into the browserbase session's user-agent and
    HTTP headers so the customer's existing posthog-js (already loaded by their site) tags
    the resulting session replay with our identifiers — filter by `$user_agent contains
    "PostHog-AgenticTest"` to find replays from a specific test/run.
    """
    try:
        client = get_llm_client(LLM_PRODUCT)
    except ValueError as exc:
        yield _final_error(str(exc))
        return

    state = _RunState()
    start = time.monotonic()

    chosen_region = _pick_region(regions)
    try:
        with open_session(region=chosen_region) as bb, sync_playwright() as pw:
            yield AgentEvent(
                "status",
                {
                    "message": f"Browserbase session opened in {bb.region}",
                    "replay_url": bb.replay_url,
                    "region": bb.region,
                },
            )
            browser = pw.chromium.connect_over_cdp(bb.connect_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            _configure_context(
                context,
                test_id=test_id,
                run_id=run_id,
                test_name=test_name,
                region=bb.region,
            )
            page = context.pages[0] if context.pages else context.new_page()
            _override_user_agent_for_page(page, test_id=test_id, run_id=run_id, region=bb.region)

            tagged_url = _append_run_tracking_params(target_url, run_id=run_id, test_id=test_id)
            page.goto(tagged_url, wait_until="domcontentloaded")
            page.wait_for_timeout(PAGE_SETTLE_MS)
            # First read attempt right after landing. May return empty if the page is an
            # interstitial (ngrok warning, consent banner) that doesn't have posthog-js.
            # We retry after each tool execution below until we get one.
            posthog_session_id = _read_posthog_session_id(page, timeout_ms=1500)
            if posthog_session_id:
                yield AgentEvent(
                    "status",
                    {
                        "message": f"Paired with PostHog session replay {posthog_session_id}",
                        "posthog_session_id": posthog_session_id,
                    },
                )
                # Let rrweb capture its first full snapshot of the landing page before
                # the agent can navigate away.
                page.wait_for_timeout(POSTHOG_RECORDER_WARMUP_MS)
            refs, snapshot = _enumerate(page)

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Test prompt: {prompt}\n\nYou are starting on: {target_url}\n\nCurrent page state:\n{snapshot}"
                    ),
                },
            ]

            while state.step < max_steps:
                state.step += 1
                resp = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    tools=TOOLS,
                    messages=messages,
                )
                if resp.usage is not None:
                    state.usage_input_tokens += resp.usage.prompt_tokens or 0
                    state.usage_output_tokens += resp.usage.completion_tokens or 0

                msg = resp.choices[0].message
                if msg.content and msg.content.strip():
                    yield AgentEvent("model_text", {"text": msg.content}, step=state.step)

                tool_calls = msg.tool_calls or []
                if not tool_calls:
                    yield from _yield_final(
                        bb,
                        state,
                        passed=False,
                        reason="Agent stopped without calling `done`.",
                        duration_ms=int((time.monotonic() - start) * 1000),
                        posthog_session_id=posthog_session_id,
                    )
                    return

                tc = tool_calls[0]
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_name = tc.function.name
                yield AgentEvent("tool_call", {"name": tool_name, "input": args}, step=state.step)

                if tool_name == "done":
                    state.actions.append({"step": state.step, "tool": "done", "input": args})
                    yield from _yield_final(
                        bb,
                        state,
                        passed=bool(args.get("passed", False)),
                        reason=str(args.get("reason", "")),
                        duration_ms=int((time.monotonic() - start) * 1000),
                        posthog_session_id=posthog_session_id,
                    )
                    return

                try:
                    result_text = _execute_tool(page, tool_name, args, refs)
                except Exception as exc:  # noqa: BLE001 — surface tool errors to the agent
                    result_text = f"Tool error: {exc}"

                state.actions.append(
                    {
                        "step": state.step,
                        "tool": tool_name,
                        "input": args,
                        "result": result_text[:500],
                    }
                )
                yield AgentEvent("tool_result", {"name": tool_name, "result": result_text[:500]}, step=state.step)

                page.wait_for_timeout(PAGE_SETTLE_MS)
                # Re-check for posthog-js if we haven't paired yet — the agent may have
                # just clicked through an interstitial (ngrok warning, cookie banner) onto
                # the actual customer site where posthog-js is loaded.
                if not posthog_session_id:
                    posthog_session_id = _read_posthog_session_id(page, timeout_ms=500)
                    if posthog_session_id:
                        yield AgentEvent(
                            "status",
                            {
                                "message": f"Paired with PostHog session replay {posthog_session_id}",
                                "posthog_session_id": posthog_session_id,
                            },
                            step=state.step,
                        )
                        # Give posthog-js's rrweb recorder time to take its first full
                        # DOM snapshot on this page. Without this delay the recording can
                        # start from the *next* page the agent navigates to.
                        page.wait_for_timeout(POSTHOG_RECORDER_WARMUP_MS)
                refs, snapshot = _enumerate(page)
                _strip_stale_snapshots(messages)

                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"{result_text}{_SNAPSHOT_MARKER}{snapshot}",
                    }
                )

            yield from _yield_final(
                bb,
                state,
                passed=False,
                reason=f"Exceeded max_steps={max_steps} without a verdict.",
                duration_ms=int((time.monotonic() - start) * 1000),
                posthog_session_id=posthog_session_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("agentic_test_runner_error", error=str(exc))
        yield _final_error(str(exc), duration_ms=int((time.monotonic() - start) * 1000))


def _execute_tool(page: Page, name: str, args: dict[str, Any], refs: dict[int, Any]) -> str:
    if name == "goto":
        page.goto(args["url"], wait_until="domcontentloaded")
        return f"Navigated to {args['url']}"
    if name == "click":
        ref = int(args["ref"])
        locator = refs.get(ref)
        if locator is None:
            raise RuntimeError(f"No element with ref={ref}; available refs: {sorted(refs.keys())[:20]}")
        locator.click(timeout=ACTION_TIMEOUT_MS)
        return f"Clicked [{ref}]"
    if name == "fill":
        ref = int(args["ref"])
        locator = refs.get(ref)
        if locator is None:
            raise RuntimeError(f"No element with ref={ref}; available refs: {sorted(refs.keys())[:20]}")
        locator.fill(args["value"], timeout=ACTION_TIMEOUT_MS)
        return f"Filled [{ref}] with {len(args['value'])} chars"
    if name == "press":
        page.keyboard.press(args["key"])
        return f"Pressed {args['key']}"
    if name == "wait":
        page.wait_for_timeout(int(args["ms"]))
        return f"Waited {args['ms']}ms"
    return f"Unknown tool: {name}"


def _strip_stale_snapshots(messages: list[dict[str, Any]]) -> None:
    """Drop the page-snapshot tail from every tool message in-place.

    Only the most recent tool-result should carry a snapshot; otherwise input
    tokens grow linearly per step and rate limits kick in.
    """
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content")
        if isinstance(content, str) and _SNAPSHOT_MARKER in content:
            m["content"] = content.split(_SNAPSHOT_MARKER, 1)[0] + "\n\n(prior page state omitted)"


def _yield_final(
    bb: BrowserbaseSession,
    state: _RunState,
    *,
    passed: bool,
    reason: str,
    duration_ms: int,
    posthog_session_id: str = "",
) -> Iterator[AgentEvent]:
    yield AgentEvent(
        "final",
        {
            "passed": passed,
            "external_session_id": bb.id,
            "screenshot_url": bb.replay_url,
            "region": bb.region,
            "posthog_session_id": posthog_session_id,
            "output": {
                "verdict": {"passed": passed, "reason": reason},
                "actions": state.actions,
                "usage": {
                    "input_tokens": state.usage_input_tokens,
                    "output_tokens": state.usage_output_tokens,
                },
                "model": MODEL,
                "duration_ms": duration_ms,
            },
        },
    )


def _final_error(message: str, *, duration_ms: int = 0) -> AgentEvent:
    return AgentEvent(
        "final",
        {
            "passed": False,
            "error": message,
            "external_session_id": "",
            "screenshot_url": "",
            "region": "",
            "posthog_session_id": "",
            "output": {"verdict": {"passed": False, "reason": message}, "actions": [], "duration_ms": duration_ms},
        },
    )


def _pick_region(regions: list[str] | None) -> str | None:
    """Pick a supported region from the configured list. None lets browserbase pick."""
    if not regions:
        return None
    candidates = [r for r in regions if r in SUPPORTED_REGIONS]
    return random.choice(candidates) if candidates else DEFAULT_REGION


_USER_AGENT_BASE = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _configure_context(
    context: BrowserContext,
    *,
    test_id: str,
    run_id: str,
    test_name: str,
    region: str,
) -> None:
    """Tag every request from this context with identifying headers so customer servers + PostHog
    session replays can filter by our run."""
    try:
        context.set_extra_http_headers(
            {
                "X-PostHog-Agentic-Test-Id": test_id,
                "X-PostHog-Agentic-Test-Run-Id": run_id,
                "X-PostHog-Agentic-Test-Region": region,
                "X-PostHog-Agentic-Test-Name": test_name[:120],
            }
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal
        logger.warning("agentic_test_headers_failed", error=str(exc))


def _append_run_tracking_params(url: str, *, run_id: str, test_id: str) -> str:
    """Append a single tracking param the customer's posthog-js will capture into `$current_url`.

    We deliberately avoid UTM (`utm_*`) so we don't pollute the customer's marketing
    analytics. `_phag=run-<id>` is unique to PostHog Agentic tests and the run id is
    enough to look the session up server-side via substring match on `$current_url`.
    """
    from urllib.parse import urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    extra = urlencode({"_phag": f"run-{run_id}"})
    new_query = f"{parsed.query}&{extra}" if parsed.query else extra
    return urlunparse(parsed._replace(query=new_query))


def _read_posthog_session_id(page: Page, *, timeout_ms: int = 4000) -> str:
    """If the customer's posthog-js is loaded on this page, return its current session id.

    Best-effort: returns empty string if posthog-js isn't present or doesn't initialize
    within the deadline (the caller falls back to the post-run CH lookup in that case).
    """
    script = """
async () => {
    const deadline = Date.now() + 4000
    while (Date.now() < deadline) {
        const sid = window.posthog && window.posthog.get_session_id && window.posthog.get_session_id()
        if (sid) return sid
        await new Promise((r) => setTimeout(r, 100))
    }
    return ''
}
"""
    try:
        sid = page.evaluate(script)
    except Exception as exc:  # noqa: BLE001 — non-fatal, lookup fallback covers us
        logger.warning("agentic_test_posthog_eager_pair_failed", error=str(exc))
        return ""
    return str(sid) if sid else ""


def _override_user_agent_for_page(page: Page, *, test_id: str, run_id: str, region: str) -> None:
    """Override navigator.userAgent on this page via CDP so the customer's posthog-js picks it up."""
    custom_ua = f"{_USER_AGENT_BASE} PostHog-AgenticTest/1.0 (test={test_id}; run={run_id}; region={region})"
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Network.setUserAgentOverride", {"userAgent": custom_ua})
    except Exception as exc:  # noqa: BLE001 — non-fatal, customer just won't see the tag
        logger.warning("agentic_test_ua_override_failed", error=str(exc))
