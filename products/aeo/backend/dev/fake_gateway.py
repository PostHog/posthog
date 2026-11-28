"""A stand-in for the AI gateway, for running AI visibility on the local stack without a gateway token.

It answers the calls AEO makes, in the shapes the parsers in `engines.py`, `suggestions.py` and
`keyword_suggestions.py` read: Anthropic `/v1/messages` (site research, prompt writing, keyword picking and the
Claude engine) and OpenAI `/v1/responses` (the OpenAI and Perplexity engines). Every answer is built from the request
and seeded by it, so the same request always gets the same answer while different prompts get different ones, and
a share of the engine answers fail or leave the site uncited so every state of the page shows up.

Run it with `python -m products.aeo.backend.dev.fake_gateway` (no Django). The README's
"Local development without a gateway token" section says how the stack reaches it.
"""

from __future__ import annotations

import os
import re
import sys
import hmac
import json
import time
import random
import hashlib
import argparse
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_PORT = 8080
# Enough latency for the wizard to show its progress states and little enough for an automated check to
# finish quickly. The realistic preset is what a person sees with the real gateway.
DEFAULT_DELAY_MS = "100"
REALISTIC_DELAY_MS = "800-3000"
DEFAULT_STORE = Path(".posthog/aeo-fake-gateway")
TOKEN_FILE = Path("~/.ai-gateway-token.json")
MAX_BODY_BYTES = 2 * 1024 * 1024
# These phrases open the three setup instructions in suggestions.py and keyword_suggestions.py. A request whose
# first user message carries none of them is an engine prompt.
RESEARCH_MARKER = "You research a company"
PROMPTS_MARKER = "choose the prompts to track"
KEYWORDS_MARKER = "choose the keywords to track"
# A domain with one of these words in it fails its setup calls, so the wizard's error states can be reached on
# purpose without making every other setup flaky.
FAIL_DOMAIN_WORD = "fail"
UNREADABLE_DOMAIN_WORD = "unreadable"

# Outcomes of an engine answer and their shares. The site is cited in most answers, named without a citation in
# some, absent from others, and a few calls fail the way the real providers fail.
OUTCOME_CITED = "cited"
OUTCOME_MENTIONED = "mentioned"
OUTCOME_ABSENT = "absent"
OUTCOME_TRUNCATED = "truncated"
OUTCOME_HTTP_ERROR = "http_error"
OUTCOME_THROTTLED = "throttled"
OUTCOME_WEIGHTS = {
    OUTCOME_CITED: 55,
    OUTCOME_MENTIONED: 15,
    OUTCOME_ABSENT: 18,
    OUTCOME_TRUNCATED: 5,
    OUTCOME_HTTP_ERROR: 4,
    OUTCOME_THROTTLED: 3,
}

CATEGORIES = (
    "product analytics",
    "session replay",
    "feature flag management",
    "customer support software",
    "project management",
    "email marketing",
    "website builder",
    "password manager",
    "expense management",
    "applicant tracking",
    "online course platform",
    "meal kit delivery",
    "running shoes",
    "home security cameras",
    "pet insurance",
)
AUDIENCES = (
    "startups",
    "small teams",
    "enterprise teams",
    "developers",
    "marketers",
    "agencies",
    "ecommerce stores",
    "remote teams",
    "freelancers",
    "families",
)
FEATURES = (
    "a free tier",
    "self-hosting",
    "SSO",
    "an API",
    "mobile apps",
    "unlimited seats",
    "GDPR compliance",
    "offline mode",
    "a generous free plan",
    "Slack integration",
)
STACKS = ("Next.js", "Shopify", "WordPress", "React Native", "Django", "Rails", "Webflow", "Flutter")
TOPICS = ("Pricing", "Alternatives", "Comparisons", "Getting started", "Integrations", "Best of")
# Invented brand words for competitors and third-party sites. None of them is a product the fake knows about.
COMPETITOR_WORDS = (
    "northquill",
    "fernlight",
    "brightmoor",
    "tidewell",
    "copperbay",
    "slatebird",
    "marrowly",
    "glintforge",
    "hollowpine",
    "ambervale",
    "quietmill",
    "driftstone",
    "lanternfox",
    "wrenfield",
    "saltmeadow",
    "ironleaf",
)
PUBLISHER_DOMAINS = (
    "reviewsgrove.com",
    "comparelyst.com",
    "stackpicks.io",
    "toolsdigest.net",
    "buyersnotebook.com",
)
PAGE_PATHS = ("", "/pricing", "/blog/getting-started", "/docs", "/compare", "/features", "/customers", "/about")


def _seed(*parts: Any) -> int:
    canonical = json.dumps(parts, sort_keys=True, default=str)
    return int.from_bytes(hashlib.sha256(canonical.encode()).digest()[:8], "big")


def _rng(*parts: Any) -> random.Random:
    return random.Random(_seed(*parts))


def brand_name(domain: str) -> str:
    """The brand people call a site: its registrable label, capitalized. `www.quillnest.com` is Quillnest."""
    host = urlparse(domain if "//" in domain else f"//{domain}").hostname or domain
    labels = [label for label in host.lower().split(".") if label]
    if len(labels) >= 2:
        # Two-part public suffixes such as co.uk hide the brand one label further in.
        if len(labels) >= 3 and len(labels[-2]) <= 3 and labels[-1] != "com":
            label = labels[-3]
        else:
            label = labels[-2]
    else:
        label = labels[0] if labels else "brand"
    return label[:1].upper() + label[1:]


def registrable(domain: str) -> str:
    host = urlparse(domain if "//" in domain else f"//{domain}").hostname or domain
    return host.lower().removeprefix("www.")


def category_for(domain: str) -> str:
    return CATEGORIES[_seed("category", registrable(domain)) % len(CATEGORIES)]


def competitors_for(domain: str, count: int = 4) -> list[dict[str, str]]:
    """Invented competitors, the same ones for a domain on every call so setup and the checks agree."""
    rng = _rng("competitors", registrable(domain))
    words = rng.sample(COMPETITOR_WORDS, count)
    return [{"name": word.capitalize(), "domain": f"{word}.com"} for word in words]


def _first_user_text(body: dict[str, Any]) -> str:
    for message in body.get("messages") or []:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    text = body.get("input")
    return text if isinstance(text, str) else ""


def _field(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}: (.+)$", text, re.MULTILINE)
    value = match.group(1).strip() if match else ""
    return "" if value.startswith("infer") or value in ("unknown", "none yet", "- none") else value


def _given_competitors(text: str) -> list[dict[str, str]]:
    given = _field(text, "Competitors")
    found: list[dict[str, str]] = []
    for raw in filter(None, (part.strip() for part in given.split(","))):
        if "." in raw and " " not in raw:
            found.append({"name": brand_name(raw), "domain": registrable(raw)})
        else:
            found.append({"name": raw, "domain": f"{re.sub(r'[^a-z0-9]', '', raw.lower()) or 'competitor'}.com"})
    return found


def _wants_pause(body: dict[str, Any], rng: random.Random) -> bool:
    # One setup call in ten pauses its turn after searching, so the continuation path runs too. A request that
    # already carries the assistant's paused content is the continuation and always finishes.
    has_assistant = any(message.get("role") == "assistant" for message in body.get("messages") or [])
    return not has_assistant and rng.random() < 0.1


# --- Anthropic /v1/messages -------------------------------------------------------------------------------------


def _usage(rng: random.Random, output_tokens: int) -> dict[str, Any]:
    return {
        "input_tokens": rng.randint(400, 2500),
        "output_tokens": output_tokens,
        "server_tool_use": {"web_search_requests": rng.randint(0, 3)},
    }


def _search_blocks(queries: list[str], results: list[tuple[str, str]], rng: random.Random) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, query in enumerate(queries):
        tool_use_id = f"srvtoolu_{rng.getrandbits(40):010x}"
        blocks.append({"type": "server_tool_use", "id": tool_use_id, "name": "web_search", "input": {"query": query}})
        blocks.append(
            {
                "type": "web_search_tool_result",
                "tool_use_id": tool_use_id,
                "content": [
                    {
                        "type": "web_search_result",
                        "url": url,
                        "title": title,
                        "encrypted_content": "",
                        "page_age": None,
                    }
                    for url, title in results[index::2] or results[:1]
                ],
            }
        )
    return blocks


def _messages_body(
    model: str,
    content: list[dict[str, Any]],
    rng: random.Random,
    *,
    stop_reason: str = "end_turn",
    output_tokens: int | None = None,
) -> dict[str, Any]:
    return {
        "id": f"msg_{rng.getrandbits(96):024x}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": _usage(rng, output_tokens if output_tokens is not None else rng.randint(300, 1500)),
    }


def _json_answer(model: str, value: Any, queries: list[str], domain: str, rng: random.Random) -> dict[str, Any]:
    results = [
        (f"https://{registrable(domain)}{path}", f"{brand_name(domain)} {path or 'home'}") for path in PAGE_PATHS[:4]
    ]
    content = [*_search_blocks(queries, results, rng), {"type": "text", "text": json.dumps(value, indent=2)}]
    return _messages_body(model, content, rng)


def setup_domain(text: str) -> str:
    """The site a setup instruction is about: the `Site:` line of the prompt and keyword instructions, or the
    domain the research instructions ask to read."""
    match = re.search(r"read (\S+) itself", text) or re.search(r"site:(\S+)", text)
    return _field(text, "Site") or (match.group(1).strip(".,:") if match else "")


def research_answer(text: str, model: str, rng: random.Random) -> dict[str, Any]:
    domain = setup_domain(text) or "example.com"
    brand = _field(text, "Brand") or brand_name(domain)
    category = category_for(domain)
    audience = AUDIENCES[_seed("audience", registrable(domain)) % len(AUDIENCES)]
    competitors = _given_competitors(text) or competitors_for(domain)
    value = {
        "brand": brand,
        "category": category,
        "description": f"{brand} sells {category} to {audience}, with {rng.choice(FEATURES)} and {rng.choice(FEATURES)}.",
        "competitors": competitors,
    }
    queries = [f"site:{registrable(domain)}", f"{brand} pricing"]
    return _json_answer(model, value, queries, domain, rng)


def _prompt_items(
    count: int, brand: str, category: str, competitors: list[str], branded_max: int, rng: random.Random
) -> list[dict[str, Any]]:
    audience = lambda: rng.choice(AUDIENCES)  # noqa: E731
    competitor = lambda: rng.choice(competitors) if competitors else "the market leader"  # noqa: E731
    unbranded = [
        (f"best {category} tool", "Best of", "table_stakes", "middle"),
        (f"best {category} for {audience()}", "Best of", "battleground", "middle"),
        (f"best {category} with {rng.choice(FEATURES)}", "Best of", "differentiation", "middle"),
        (f"top {category} software in 2026", "Best of", "table_stakes", "top"),
        (f"best {competitor()} alternatives", "Alternatives", "battleground", "bottom"),
        (f"cheaper alternatives to {competitor()}", "Alternatives", "vulnerability", "bottom"),
        (f"cheapest {category} tool for {audience()}", "Pricing", "vulnerability", "bottom"),
        (f"free {category} tools", "Pricing", "vulnerability", "top"),
        (f"which {category} tool should I use for {rng.choice(STACKS)}?", "Getting started", "battleground", "middle"),
        (f"which {category} tool is easiest to set up?", "Getting started", "differentiation", "middle"),
        (f"how do I choose a {category} tool?", "Getting started", "table_stakes", "top"),
        (f"{category} tools that integrate with {rng.choice(STACKS)}", "Integrations", "battleground", "middle"),
        (f"open source {category} tools", "Alternatives", "differentiation", "top"),
        (f"{category} for {audience()} reviews", "Comparisons", "battleground", "middle"),
        (f"what is {category}?", "Getting started", "table_stakes", "top"),
        (f"is {competitor()} worth it?", "Comparisons", "vulnerability", "bottom"),
        (f"{category} pricing comparison", "Pricing", "table_stakes", "middle"),
        (f"{category} with {rng.choice(FEATURES)} and {rng.choice(FEATURES)}", "Best of", "differentiation", "middle"),
        (f"most popular {category} tool", "Best of", "battleground", "top"),
        (f"{competitor()} vs {competitor()}", "Comparisons", "battleground", "bottom"),
    ]
    branded = [
        (f"{brand} vs {competitor()}", "Comparisons", "branded", "bottom"),
        (f"{brand} pricing", "Pricing", "branded", "bottom"),
        (f"is {brand} free?", "Pricing", "branded", "middle"),
        (f"is {brand} good for {audience()}?", "Comparisons", "branded", "middle"),
        (f"{brand} vs {competitor()} for {audience()}", "Comparisons", "branded", "bottom"),
    ]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(source: list[tuple[str, str, str, str]], limit: int) -> None:
        for prompt, topic, circle, stage in source:
            if len(items) >= limit or prompt.lower() in seen:
                continue
            seen.add(prompt.lower())
            items.append(
                {
                    "prompt": prompt,
                    "topic": topic,
                    "circle": circle,
                    "funnel_stage": stage,
                    "branded": circle == "branded",
                    "reason": f"Buyers ask this when they compare {category} options.",
                }
            )

    add(unbranded, count - min(branded_max, len(branded)))
    add(branded, count)
    # Long sets outgrow the templates, so the rest are numbered variations of the best-of prompt.
    extra = 1
    while len(items) < count:
        add([(f"best {category} tool for {audience()} (option {extra})", "Best of", "battleground", "middle")], count)
        extra += 1
    return items


def prompts_answer(text: str, model: str, rng: random.Random) -> dict[str, Any]:
    domain = _field(text, "Site") or "example.com"
    count_match = re.search(r"write (\d+) prompts", text)
    count = int(count_match.group(1)) if count_match else 20
    branded_match = re.search(r"at most (\d+) branded prompts", text)
    branded_max = int(branded_match.group(1)) if branded_match else max(1, count // 5)
    if "Do not name" in text and "in any prompt" in text:
        branded_max = 0
    brand = _field(text, "Brand") or brand_name(domain)
    category = _field(text, "Category") or category_for(domain)
    competitors = _given_competitors(text) or competitors_for(domain)
    value = {
        "competitors": competitors,
        "prompts": _prompt_items(count, brand, category, [c["name"] for c in competitors], branded_max, rng),
    }
    return _json_answer(model, value, [f"{brand} {category}"], domain, rng)


def _searched_queries(text: str) -> list[str]:
    section = text.split("Web searches the assistants ran", 1)
    if len(section) < 2:
        return []
    lines = section[1].split("Keywords the team already tracks", 1)[0].splitlines()
    return [
        re.sub(r"\s*\(\d+\)\s*$", "", line[2:]).strip() for line in lines if line.startswith("- ") and line != "- none"
    ]


def keywords_answer(text: str, model: str, rng: random.Random) -> dict[str, Any]:
    domain = _field(text, "Site") or "example.com"
    count_match = re.search(r"choose the (\d+) keywords", text)
    count = int(count_match.group(1)) if count_match else 20
    category = category_for(domain)
    head = category.split()[-1]
    candidates = [
        *(_plain_keyword(query) for query in _searched_queries(text)),
        category,
        f"{category} tools",
        f"{category} software",
        f"best {category}",
        f"{category} pricing",
        f"free {category}",
        f"open source {category}",
        f"{category} alternatives",
        f"{category} for startups",
        f"{category} comparison",
        f"{head} platform",
        f"{head} dashboard",
        f"self-hosted {category}",
        f"{category} api",
        f"{category} integrations",
        f"enterprise {category}",
        f"{category} reviews",
        f"{category} trial",
        f"cheap {category}",
        f"{head} analytics",
        f"{head} automation",
        f"{head} templates",
        f"{head} onboarding",
        f"{head} security",
        f"{head} reporting",
    ]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for keyword in candidates:
        keyword = " ".join(keyword.lower().split())
        if not keyword or keyword in seen or len(keyword.split()) > 4:
            continue
        seen.add(keyword)
        items.append({"keyword": keyword, "reason": f"Buyers type this when they look for {category}."})
        # The parser drops keywords that name the brand or that the list has, and caps at the count itself.
        if len(items) >= count + 5:
            break
    return _json_answer(model, items, [f"{category} keywords"], domain, rng)


def _plain_keyword(query: str) -> str:
    words = [word for word in re.sub(r"[^a-z0-9 -]", "", query.lower()).split() if word not in ("best", "for", "the")]
    return " ".join(words[:4])


# --- Engine answers ---------------------------------------------------------------------------------------------


def _pick_outcome(rng: random.Random) -> str:
    return rng.choices(list(OUTCOME_WEIGHTS), weights=list(OUTCOME_WEIGHTS.values()))[0]


class EngineAnswer:
    """What one engine says to one prompt, before it is put into a provider's shape."""

    def __init__(self, prompt: str, domain: str, rng: random.Random, outcome: str) -> None:
        self.outcome = outcome
        self.domain = registrable(domain)
        self.brand = brand_name(domain)
        self.competitors = competitors_for(domain)
        others = rng.sample(self.competitors, rng.randint(2, min(4, len(self.competitors))))
        self.queries = [prompt.rstrip("?")]
        for extra in (f"{prompt.rstrip('?')} reviews", f"{others[0]['name']} vs {self.brand}"):
            if rng.random() < 0.5:
                self.queries.append(extra)
        self.queries = self.queries[:3]
        # The brand sits in a different position in each answer, so rankings have something to rank.
        names = [other["name"] for other in others]
        if outcome in (OUTCOME_CITED, OUTCOME_MENTIONED):
            names.insert(rng.randint(0, len(names)), self.brand)
        self.names = names
        self.sentences = [
            f"If you are looking for {category_for(domain)}, {names[0]} is the option most people start with.",
            *(
                f"{name} {rng.choice(('is a strong pick', 'stands out', 'is worth a look', 'gets good reviews'))} "
                f"{rng.choice(('for small teams', 'if you need an API', 'on price', 'for ease of setup'))}."
                for name in names[1:]
            ),
            f"{rng.choice(('In short', 'Overall', 'For most teams'))}, {names[-1]} and {names[0]} are the safest bets.",
        ]
        cited: list[str] = []
        if outcome == OUTCOME_CITED:
            for path in rng.sample(PAGE_PATHS, rng.randint(1, 2)):
                cited.append(f"https://{self.domain}{path}")
        for other in others:
            if rng.random() < 0.7:
                cited.append(f"https://{other['domain']}{rng.choice(PAGE_PATHS)}")
        if rng.random() < 0.6:
            cited.append(f"https://{rng.choice(PUBLISHER_DOMAINS)}/best-{category_for(domain).replace(' ', '-')}")
        rng.shuffle(cited)
        cited = list(dict.fromkeys(cited))
        fallbacks = [f"https://{other['domain']}/pricing" for other in others]
        fallbacks += [f"https://{publisher}/reviews" for publisher in PUBLISHER_DOMAINS]
        for url in fallbacks:
            if len(cited) >= 2:
                break
            if url not in cited:
                cited.append(url)
        self.cited = cited[:6]
        self.retrieved = [*self.cited, f"https://{rng.choice(PUBLISHER_DOMAINS)}/reviews"]

    def citations_per_sentence(self) -> list[list[str]]:
        per_sentence: list[list[str]] = [[] for _ in self.sentences]
        for index, url in enumerate(self.cited):
            per_sentence[index % len(self.sentences)].append(url)
        return per_sentence


def engine_outcome(prompt: str, model: str) -> str:
    """The seeded outcome of one prompt on one model, shared by every provider shape."""
    return _pick_outcome(_rng("outcome", prompt, model))


def _engine_answer(body: dict[str, Any], domain: str, rng: random.Random, outcome: str) -> EngineAnswer:
    return EngineAnswer(_first_user_text(body), domain, rng, outcome)


def claude_check_answer(body: dict[str, Any], domain: str, rng: random.Random, outcome: str) -> dict[str, Any]:
    model = str(body.get("model") or "claude")
    answer = _engine_answer(body, domain, rng, outcome)
    searching = bool(body.get("tools"))
    if outcome == OUTCOME_TRUNCATED:
        content = [
            *(_search_blocks(answer.queries[:1], [(url, url) for url in answer.retrieved], rng) if searching else []),
            {"type": "text", "text": "Here is what I found so far: " + answer.sentences[0][:40]},
        ]
        return _messages_body(
            model, content, rng, stop_reason="max_tokens", output_tokens=int(body.get("max_tokens", 1))
        )
    if not searching:
        return _messages_body(model, [{"type": "text", "text": " ".join(answer.sentences)}], rng)
    content = _search_blocks(answer.queries, [(url, url) for url in answer.retrieved], rng)
    for sentence, urls in zip(answer.sentences, answer.citations_per_sentence()):
        block: dict[str, Any] = {"type": "text", "text": sentence + " "}
        if urls:
            block["citations"] = [
                {
                    "type": "web_search_result_location",
                    "url": url,
                    "title": url.split("//", 1)[-1],
                    "encrypted_index": "",
                    "cited_text": sentence[:60],
                }
                for url in urls
            ]
        content.append(block)
    return _messages_body(model, content, rng)


# --- OpenAI and Perplexity /v1/responses --------------------------------------------------------------------------


def _responses_body(model: str, output: list[dict[str, Any]], rng: random.Random, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"resp_{rng.getrandbits(96):024x}",
        "object": "response",
        "created_at": 1_700_000_000 + rng.randrange(100_000_000),
        "status": "completed",
        "model": model,
        "output": output,
        "usage": {
            "input_tokens": rng.randint(50, 400),
            "output_tokens": rng.randint(200, 1200),
            "total_tokens": 0,
        },
        **extra,
    }


def openai_check_answer(body: dict[str, Any], domain: str, rng: random.Random, outcome: str) -> dict[str, Any]:
    model = str(body.get("model") or "gpt")
    answer = _engine_answer(body, domain, rng, outcome)
    searching = bool(body.get("tools"))
    if outcome == OUTCOME_TRUNCATED:
        return {
            **_responses_body(
                model, [{"type": "reasoning", "id": f"rs_{rng.getrandbits(40):010x}", "summary": []}], rng
            ),
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        }
    output: list[dict[str, Any]] = []
    text = ""
    annotations: list[dict[str, Any]] = []
    if searching:
        for query in answer.queries:
            output.append(
                {
                    "type": "web_search_call",
                    "id": f"ws_{rng.getrandbits(40):010x}",
                    "status": "completed",
                    "action": {"type": "search", "query": query},
                }
            )
    for sentence, urls in zip(answer.sentences, answer.citations_per_sentence()):
        text += sentence + " "
        if searching:
            for url in urls:
                annotations.append(
                    {
                        "type": "url_citation",
                        "start_index": max(0, len(text) - len(sentence) - 1),
                        "end_index": len(text) - 1,
                        # OpenAI tags the links it cites; the parser must drop the tag before comparing URLs.
                        "url": url + ("&" if "?" in url else "?") + "utm_source=openai",
                        "title": url.split("//", 1)[-1],
                    }
                )
    output.append(
        {
            "type": "message",
            "id": f"msg_{rng.getrandbits(40):010x}",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text.strip(), "annotations": annotations}],
        }
    )
    return _responses_body(model, output, rng)


def perplexity_check_answer(body: dict[str, Any], domain: str, rng: random.Random, outcome: str) -> dict[str, Any]:
    model = str(body.get("model") or "perplexity")
    answer = _engine_answer(body, domain, rng, outcome)
    if outcome == OUTCOME_TRUNCATED:
        return {
            **_responses_body(model, [], rng),
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        }
    results = [
        {"id": index + 1, "url": url, "title": url.split("//", 1)[-1], "snippet": "", "date": None}
        for index, url in enumerate(answer.retrieved)
    ]
    ids_by_url = {result["url"]: result["id"] for result in results}
    text = ""
    for sentence, urls in zip(answer.sentences, answer.citations_per_sentence()):
        text += sentence + "".join(f"[{ids_by_url[url]}]" for url in urls) + " "
    output = [
        {
            "type": "search_results",
            "id": f"sr_{rng.getrandbits(40):010x}",
            "queries": answer.queries,
            "results": results,
        },
        {
            "type": "message",
            "id": f"msg_{rng.getrandbits(40):010x}",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text.strip(), "annotations": []}],
        },
    ]
    cost = round(rng.uniform(0.004, 0.02), 4)
    extra = {"usage": {"input_tokens": 100, "output_tokens": 300, "cost": {"total_cost": cost}}}
    return {**_responses_body(model, output, rng), **extra}


# --- Request handling ---------------------------------------------------------------------------------------------


class GatewayResponse:
    def __init__(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}


def _error(status: int, message: str, kind: str = "api_error") -> GatewayResponse:
    return GatewayResponse(status, {"type": "error", "error": {"type": kind, "message": message}})


def classify(path: str, body: dict[str, Any]) -> str:
    """Which AEO call a request is: research, prompts, keywords, claude, openai or perplexity."""
    if path.rstrip("/").endswith("/responses"):
        model = str(body.get("model") or "")
        tools = body.get("tools") or []
        if "perplexity" in model.lower() or any("search_type" in tool for tool in tools):
            return "perplexity"
        return "openai"
    text = _first_user_text(body)
    if RESEARCH_MARKER in text:
        return "research"
    if PROMPTS_MARKER in text:
        return "prompts"
    if KEYWORDS_MARKER in text:
        return "keywords"
    return "claude"


class FakeGateway:
    """Builds the answer to one request. `domains` are the sites checks may cite, the most recent setup first."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.domains: list[str] = []
        self._throttled: set[int] = set()

    def remember_domain(self, domain: str) -> None:
        with self._lock:
            if domain in self.domains:
                self.domains.remove(domain)
            self.domains.insert(0, domain)
            del self.domains[20:]

    def note_setup(self, path: str, body: dict[str, Any]) -> None:
        """Remembers the site a setup call is about, so the engine answers that follow cite it."""
        if classify(path, body) in ("research", "prompts", "keywords"):
            domain = setup_domain(_first_user_text(body))
            if domain:
                self.remember_domain(registrable(domain))

    def _check_domain(self, body: dict[str, Any]) -> str:
        """The site an engine answer is about. The prompt rarely names it, so the fake uses the site set up most
        recently, or a brand named in the prompt, or an invented one."""
        prompt = _first_user_text(body).lower()
        with self._lock:
            for domain in self.domains:
                if brand_name(domain).lower() in prompt:
                    return domain
            if self.domains:
                return self.domains[0]
        return os.environ.get("FAKE_GATEWAY_DEFAULT_DOMAIN", "example.com")

    def handle(self, path: str, body: dict[str, Any]) -> GatewayResponse:
        kind = classify(path, body)
        text = _first_user_text(body)
        model = str(body.get("model") or "model")
        rng = _rng(kind, path, text, model, body.get("tools"))
        if kind in ("research", "prompts", "keywords"):
            domain = setup_domain(text)
            self.note_setup(path, body)
            if FAIL_DOMAIN_WORD in domain:
                return _error(500, "the fake gateway fails setup calls for domains that contain 'fail'")
            if UNREADABLE_DOMAIN_WORD in domain:
                content = [{"type": "text", "text": "I could not find a JSON answer for this site, sorry."}]
                return GatewayResponse(200, _messages_body(model, content, rng))
            if _wants_pause(body, rng):
                blocks = _search_blocks([f"site:{domain}"], [(f"https://{domain}/", domain)], rng)
                return GatewayResponse(200, _messages_body(model, blocks, rng, stop_reason="pause_turn"))
            setup_builder = {"research": research_answer, "prompts": prompts_answer, "keywords": keywords_answer}[kind]
            return GatewayResponse(200, setup_builder(text, model, rng))

        outcome = engine_outcome(text, model)
        if outcome == OUTCOME_HTTP_ERROR:
            return _error(400, "the fake gateway fails a few engine calls on purpose", "invalid_request_error")
        if outcome == OUTCOME_THROTTLED:
            # Retryable, so the engine's backoff runs; the next attempt is a different request only if the
            # body changes, so the retry is seeded on the attempt count the server keeps per prompt.
            if self._throttle_once(text, model):
                response = _error(429, "the fake gateway throttles a few engine calls once", "rate_limit_error")
                response.headers["Retry-After"] = "1"
                return response
            outcome = OUTCOME_CITED
        domain = self._check_domain(body)
        check_builder = {
            "claude": claude_check_answer,
            "openai": openai_check_answer,
            "perplexity": perplexity_check_answer,
        }[kind]
        return GatewayResponse(200, check_builder(body, domain, rng, outcome))

    def _throttle_once(self, text: str, model: str) -> bool:
        key = _seed("throttle", text, model)
        with self._lock:
            if key in self._throttled:
                return False
            self._throttled.add(key)
            return True


# --- Record and replay --------------------------------------------------------------------------------------------


def request_key(path: str, body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([path, body], sort_keys=True).encode()).hexdigest()


class Recorder:
    """Forwards requests to the real gateway with the token in ~/.ai-gateway-token.json and keeps the answers.
    The token is read once and never written anywhere, including logs."""

    def __init__(self, store: Path, token_file: Path | None = None) -> None:
        self.store = store
        self.store.mkdir(parents=True, exist_ok=True)
        token_file = token_file or TOKEN_FILE
        data = json.loads(token_file.expanduser().read_text())
        self._token: str = data["token"]
        self.root = str(data.get("gateway_url", "")).rstrip("/").removesuffix("/v1")
        if not self.root or not self._token:
            raise SystemExit(f"{token_file} needs 'gateway_url' and 'token'")

    def forward(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> GatewayResponse:
        outgoing = {
            key: value
            for key, value in headers.items()
            if key.lower() in ("anthropic-version", "content-type") or key.lower().startswith("x-posthog-")
        }
        outgoing["Authorization"] = f"Bearer {self._token}"
        outgoing["Content-Type"] = "application/json"
        upstream = requests.post(self.root + path, data=json.dumps(body).encode(), headers=outgoing, timeout=420)
        try:
            payload = upstream.json() if upstream.content else {}
        except ValueError:
            payload = {"error": {"message": upstream.text[:500]}}
        # The runner reads the denial and retry headers to tell exhausted credits and throttling from other errors.
        kept = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() == "retry-after" or key.lower().startswith("x-posthog-")
        }
        response = GatewayResponse(upstream.status_code, payload, kept)
        if response.status == 200:
            self._keep(request_key(path, body), {"path": path, "request": body, "response": response.body})
        return response

    def _keep(self, key: str, recording: dict[str, Any]) -> None:
        # Two identical requests in flight share a file; each writes its own and the last rename wins whole.
        partial = self.store / f".{key}.{threading.get_ident()}.part"
        partial.write_text(json.dumps(recording, indent=2))
        os.replace(partial, self.store / f"{key}.json")


class Replayer:
    def __init__(self, store: Path) -> None:
        self.store = store

    def lookup(self, path: str, body: dict[str, Any]) -> GatewayResponse | None:
        file = self.store / f"{request_key(path, body)}.json"
        if not file.exists():
            return None
        return GatewayResponse(200, json.loads(file.read_text())["response"])


# --- Server -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class Delay:
    """How long each answer waits, in seconds, drawn uniformly between the two bounds."""

    low: float = 0.0
    high: float = 0.0


NO_DELAY = Delay()


def parse_delay(spec: str | None) -> Delay:
    """`FAKE_GATEWAY_DELAY_MS` as a range in seconds: `800-3000`, or one number for a fixed delay."""
    if not spec:
        return NO_DELAY
    low, _, high = spec.partition("-")
    low_ms = float(low or 0)
    high_ms = float(high) if high else low_ms
    return Delay(low=low_ms / 1000, high=max(low_ms, high_ms) / 1000)


def content_length(headers: Mapping[str, str]) -> int | None:
    """The body size a POST declares, or None when it declares none or not a whole number; a negative or
    non-numeric value would otherwise turn into an unbounded read."""
    lowered = {key.lower(): value for key, value in headers.items()}
    declared = lowered.get("content-length", "").strip()
    if not declared.isdigit():
        return None
    if len(declared) > len(str(MAX_BODY_BYTES)):
        # Longer than the bound can ever be, and past a few thousand digits `int` refuses the string outright.
        return MAX_BODY_BYTES + 1
    try:
        return int(declared)
    except ValueError:
        return None


def refuse(headers: Mapping[str, str], record_key: str | None) -> GatewayResponse | None:
    """Why a request gets no answer: no usable body size, too large, sent by a browser, or unauthenticated while a
    real token is in play. Browsers send `Origin` or `Sec-Fetch-Mode` on every fetch and the stack's server-side
    calls send neither, so a page cannot spend the developer's token through a cross-origin POST."""
    length = content_length(headers)
    if length is None:
        return _error(400, "a POST needs a whole-number Content-Length", "invalid_request_error")
    if length > MAX_BODY_BYTES:
        return _error(413, f"the fake gateway reads at most {MAX_BODY_BYTES} bytes", "invalid_request_error")
    lowered = {key.lower(): value for key, value in headers.items()}
    if "origin" in lowered or "sec-fetch-mode" in lowered:
        return _error(403, "the fake gateway does not answer browsers", "permission_error")
    if record_key is not None:
        sent = lowered.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(sent.encode(), record_key.encode()):
            return _error(
                401, "record mode needs `Authorization: Bearer $FAKE_GATEWAY_API_KEY`", "authentication_error"
            )
    return None


class _Handler(BaseHTTPRequestHandler):
    server: FakeGatewayServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if self.server.quiet:
            return
        sys.stderr.write("[fake-gateway] " + format % args + "\n")

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        """Each POST logs its own line with the call kind, so the default request line would repeat it."""

    def _send(self, response: GatewayResponse, mode: str) -> None:
        payload = json.dumps(response.body).encode()
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Fake-Gateway", mode)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        body = {"ok": True, "mode": self.server.mode, "domains": self.server.gateway.domains}
        self._send(GatewayResponse(200, body), self.server.mode)

    def do_POST(self) -> None:  # noqa: N802
        headers = dict(self.headers.items())
        refused = refuse(headers, self.server.record_key)
        if refused is not None:
            self.close_connection = True
            self._send(refused, self.server.mode)
            return
        try:
            body = json.loads(self.rfile.read(content_length(headers) or 0) or b"{}")
        except json.JSONDecodeError:
            self._send(_error(400, "body is not JSON", "invalid_request_error"), self.server.mode)
            return
        path = urlparse(self.path).path
        if not (path.endswith("/messages") or path.endswith("/responses")):
            self._send(
                _error(404, f"the fake gateway serves /v1/messages and /v1/responses, not {path}"), self.server.mode
            )
            return
        response, mode = self.server.answer(path, body, dict(self.headers.items()))
        delay = self.server.delay
        if delay.high:
            time.sleep(random.uniform(delay.low, delay.high))
        kind = classify(path, body)
        self.log_message("%s %s -> %s (%s)", kind, path, response.status, mode)
        self._send(response, mode)


class FakeGatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        mode: str = "generated",
        store: Path = DEFAULT_STORE,
        delay: Delay = NO_DELAY,
        quiet: bool = False,
        record_key: str | None = None,
        token_file: Path | None = None,
    ) -> None:
        if mode == "record":
            if not record_key:
                raise SystemExit("record mode spends a real token, so it needs FAKE_GATEWAY_API_KEY set to a secret")
            if address[0] not in ("127.0.0.1", "localhost", "::1"):
                raise SystemExit("record mode listens on the loopback interface only")
        super().__init__(address, _Handler)
        self.mode = mode
        self.delay = delay
        self.quiet = quiet
        self.record_key = record_key if mode == "record" else None
        self.gateway = FakeGateway()
        self.recorder = Recorder(store, token_file) if mode == "record" else None
        self.replayer = Replayer(store) if mode == "replay" else None

    def answer(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[GatewayResponse, str]:
        if self.recorder is not None:
            self.gateway.note_setup(path, body)
            return self.recorder.forward(path, body, headers), "record"
        if self.replayer is not None:
            recorded = self.replayer.lookup(path, body)
            if recorded is not None:
                self.gateway.note_setup(path, body)
                return recorded, "replay"
        return self.gateway.handle(path, body), "generated"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fake AI gateway for AI visibility on the local stack.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FAKE_GATEWAY_PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default="127.0.0.1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--record",
        action="store_true",
        help="forward to the real gateway and keep the answers; callers must send FAKE_GATEWAY_API_KEY as the bearer",
    )
    mode.add_argument("--replay", action="store_true", help="serve kept answers, generating the ones never recorded")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE, help="where recorded answers live")
    parser.add_argument(
        "--delay-ms",
        default=os.environ.get("FAKE_GATEWAY_DELAY_MS", DEFAULT_DELAY_MS),
        help=f"latency per request, a fixed number of milliseconds or a range such as {REALISTIC_DELAY_MS} "
        f"(default {DEFAULT_DELAY_MS})",
    )
    parser.add_argument(
        "--realistic", action="store_true", help=f"the latency of the real gateway: --delay-ms {REALISTIC_DELAY_MS}"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    run_mode = "record" if args.record else "replay" if args.replay else "generated"
    delay_spec = REALISTIC_DELAY_MS if args.realistic else args.delay_ms
    server = FakeGatewayServer(
        (args.host, args.port),
        mode=run_mode,
        store=args.store,
        delay=parse_delay(delay_spec),
        quiet=args.quiet,
        record_key=os.environ.get("FAKE_GATEWAY_API_KEY"),
    )
    sys.stderr.write(
        f"[fake-gateway] {run_mode} mode listening on http://{args.host}:{args.port}/v1, delay {delay_spec} ms\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
