from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.utils.dateparse import parse_datetime

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.ai.session_batch_events_query_runner import (
    SessionBatchEventsQueryRunner,
    create_session_batch_events_query,
)
from posthog.llm.gateway_client import get_llm_client
from posthog.models.comment import Comment

from products.conversations.backend.services.ai_suggest_schema import (
    RefinedQuerySchema,
    ResponseValidationSchema,
    SuggestedReplySchema,
)
from products.conversations.backend.services.prompts.generate_response_system import GENERATE_RESPONSE_SYSTEM_PROMPT
from products.conversations.backend.services.prompts.refine_query_system import REFINE_QUERY_SYSTEM_PROMPT
from products.conversations.backend.services.prompts.validate_response_system import VALIDATE_RESPONSE_SYSTEM_PROMPT

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.conversations.backend.models import Ticket

logger = structlog.get_logger(__name__)

MAX_CONVERSATION_CHARS = 8000
MAX_MESSAGES = 50
MAX_EVENTS_CONTEXT = 30
MAX_EXCEPTIONS_CONTEXT = 10

LLM_MODEL = "gpt-4.1-mini"
LLM_TIMEOUT = 45.0
MAX_RETRIES = 2  # Per-call retry limit for transient LLM failures

DECLINE_RESPONSE = "I'm not able to help with that request. Please reach out to a human support agent for assistance."


def _get_author_label(message: Comment) -> str:
    ctx = message.item_context or {}
    author_type = ctx.get("author_type", "customer")
    is_private = ctx.get("is_private", False)

    if author_type == "customer":
        return "Customer"
    if is_private:
        return "Support (private note)"
    return "Support"


def format_conversation(ticket: Ticket, messages: Iterable[Comment]) -> str:
    parts: list[str] = []

    current_url = None
    if ticket.session_context and isinstance(ticket.session_context, dict):
        current_url = ticket.session_context.get("current_url")

    if current_url:
        parts.append(f"The customer was on the page: {current_url}")
        parts.append("")

    parts.append("Conversation:")

    truncated: list[str] = []
    total_messages = 0
    for msg in messages:
        label = _get_author_label(msg)
        content = (msg.content or "").strip()
        if content:
            truncated.append(f"[{label}]: {content}")
            total_messages += 1

    truncated = truncated[-MAX_MESSAGES:]
    messages_truncated = total_messages > MAX_MESSAGES

    total_chars = 0
    kept: list[str] = []
    for line in reversed(truncated):
        if total_chars + len(line) > MAX_CONVERSATION_CHARS:
            break
        kept.append(line)
        total_chars += len(line)
    kept.reverse()

    if messages_truncated or len(kept) < len(truncated):
        parts.append("[Note: Earlier messages were truncated due to length limits]")
        parts.append("")

    parts.extend(kept)
    return "\n".join(parts)


def _fetch_session_events(team: Team, session_id: str, ticket_created_at: str | None) -> list[dict]:
    """Fetch recent events for a session from ClickHouse."""
    if ticket_created_at:
        # Parse ISO format datetime safely
        created_at = parse_datetime(ticket_created_at)
        if not created_at:
            created_at = datetime.fromisoformat(ticket_created_at.replace("Z", "+00:00"))
        after = (created_at - timedelta(minutes=5)).isoformat()
        before = (created_at + timedelta(minutes=5)).isoformat()
    else:
        after = "-24h"
        before = None

    query = create_session_batch_events_query(
        session_ids=[session_id],
        select=["event", "timestamp", "properties.$current_url", "properties.$pathname"],
        events_to_ignore=["$feature_flag_called", "$pageleave", "$pageview"],
        after=after,
        before=before,
        max_total_events=MAX_EVENTS_CONTEXT,
        group_by_session=False,
    )

    runner = SessionBatchEventsQueryRunner(query=query, team=team)
    response = runner.calculate()

    events = []
    columns = response.columns or []
    for row in response.results or []:
        event_data = dict(zip(columns, row, strict=False))
        events.append(event_data)

    return events


def _fetch_session_exceptions(team: Team, session_id: str, ticket_created_at: str | None) -> list[dict]:
    """Fetch exceptions for a session from ClickHouse."""
    if ticket_created_at:
        created_at = parse_datetime(ticket_created_at)
        if not created_at:
            created_at = datetime.fromisoformat(ticket_created_at.replace("Z", "+00:00"))
        after = (created_at - timedelta(minutes=5)).isoformat()
        before = (created_at + timedelta(minutes=5)).isoformat()
    else:
        after = "-24h"
        before = None

    query = create_session_batch_events_query(
        session_ids=[session_id],
        select=[
            "event",
            "timestamp",
            "properties.$exception_message",
            "properties.$exception_type",
            "properties.$current_url",
        ],
        events_to_ignore=[],
        after=after,
        before=before,
        max_total_events=MAX_EXCEPTIONS_CONTEXT,
        group_by_session=False,
        event="$exception",
    )

    runner = SessionBatchEventsQueryRunner(query=query, team=team)
    response = runner.calculate()

    exceptions = []
    columns = response.columns or []
    for row in response.results or []:
        exc_data = dict(zip(columns, row, strict=False))
        exceptions.append(exc_data)

    return exceptions


def _format_enhanced_context(
    conversation_text: str,
    events: list[dict],
    exceptions: list[dict],
) -> str:
    """Format the conversation with additional technical context."""
    parts = [conversation_text]

    if exceptions:
        parts.append("\n\nRecent exceptions from the user's session:")
        for exc in exceptions[-MAX_EXCEPTIONS_CONTEXT:]:
            exc_type = exc.get("properties.$exception_type") or exc.get("$exception_type") or "Unknown"
            exc_msg = exc.get("properties.$exception_message") or exc.get("$exception_message") or "No message"
            url = exc.get("properties.$current_url") or exc.get("$current_url") or ""
            ts = exc.get("timestamp", "")
            parts.append(f"- [{ts}] {exc_type}: {exc_msg} (on {url})")

    if events:
        parts.append("\n\nRecent events from the user's session:")
        for evt in events[-MAX_EVENTS_CONTEXT:]:
            event_name = evt.get("event", "unknown")
            url = evt.get("properties.$current_url") or evt.get("$current_url") or ""
            ts = evt.get("timestamp", "")
            parts.append(f"- [{ts}] {event_name} (on {url})")

    return "\n".join(parts)


def _llm_call_with_retry(client, messages: list[dict], response_format, max_tokens: int | None = None):
    """Execute an LLM call with exponential-backoff retry on transient failures."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            kwargs: dict = {
                "model": LLM_MODEL,
                "messages": messages,
                "response_format": response_format,
                "timeout": LLM_TIMEOUT,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            completion = client.beta.chat.completions.parse(**kwargs)
            parsed = completion.choices[0].message.parsed
            if not parsed:
                raise ValueError(f"Failed to parse {response_format.__name__} response")
            return parsed, completion
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait_time = 2**attempt
                logger.warning(
                    "LLM call failed, retrying",
                    extra={"attempt": attempt, "wait_time": wait_time, "error_type": type(e).__name__},
                )
                time.sleep(wait_time)
            else:
                raise
    raise RuntimeError("Unreachable")


class AISuggestPipeline:
    """
    Multi-phase RAG pipeline for generating AI-suggested replies.

    Phases:
    1. Refine Query — safety check, classification, query optimization
    2. Retrieve Content — session events/exceptions + future content sources
    3. Generate Response — LLM generation with all context
    4. Validate Response — quality/groundedness check

    Retries the full pipeline up to MAX_PIPELINE_ATTEMPTS times if validation fails.
    """

    MAX_PIPELINE_ATTEMPTS = 3

    def __init__(self, ticket: Ticket, messages: list[Comment], team: Team, user_distinct_id: str):
        self.ticket = ticket
        self.team = team
        self.user_distinct_id = user_distinct_id
        self.client = get_llm_client(product="django")
        self.conversation_text = format_conversation(ticket, messages)

        self.refined_query: RefinedQuerySchema | None = None
        self.retrieved_context: str | None = None
        self.generated_reply: str | None = None
        self.validation: ResponseValidationSchema | None = None

    def run(self) -> str:
        """Execute the full pipeline with outer retry loop."""
        for attempt in range(self.MAX_PIPELINE_ATTEMPTS):
            # Phase 1: Refine query (safety + classification + optimization)
            self.refined_query = self._refine_query()

            if not self.refined_query.is_safe:
                logger.info(
                    "Query declined by safety check",
                    extra={
                        "ticket_id": str(self.ticket.id),
                        "decline_reason": self.refined_query.decline_reason,
                    },
                )
                return DECLINE_RESPONSE

            # Phase 2: Retrieve relevant content
            self.retrieved_context = self._retrieve_content()

            # Phase 3: Generate response
            self.generated_reply = self._generate_response()

            # Phase 4: Validate response
            self.validation = self._validate_response()

            if self.validation.is_valid:
                return self.generated_reply

            logger.warning(
                "Pipeline validation failed, retrying",
                extra={
                    "ticket_id": str(self.ticket.id),
                    "attempt": attempt,
                    "issue_count": len(self.validation.issues),
                },
            )

        logger.warning(
            "All pipeline attempts exhausted, returning last generated reply",
            extra={"ticket_id": str(self.ticket.id)},
        )
        # Return best-effort reply rather than failing entirely
        assert self.generated_reply is not None
        return self.generated_reply

    # -- Phase 1: Refine Query --

    def _refine_query(self) -> RefinedQuerySchema:
        """Safety check + classify + optimize the customer query in a single LLM call."""
        parsed, _ = _llm_call_with_retry(
            self.client,
            messages=[
                {"role": "system", "content": REFINE_QUERY_SYSTEM_PROMPT},
                {"role": "user", "content": self.conversation_text},
            ],
            response_format=RefinedQuerySchema,
        )
        return parsed

    # -- Phase 2: Retrieve Content --

    def _retrieve_content(self) -> str:
        """Gather all relevant context for response generation."""
        assert self.refined_query is not None

        context = self.conversation_text
        events: list[dict] = []
        exceptions: list[dict] = []

        # 2.5: Fetch session events and exceptions for issues
        if self.refined_query.conversation_type.value == "issue" and self.ticket.session_id:
            try:
                events = _fetch_session_events(self.team, self.ticket.session_id, self.ticket.created_at.isoformat())
            except Exception:
                capture_exception(additional_properties={"ticket_id": str(self.ticket.id)})

            try:
                exceptions = _fetch_session_exceptions(
                    self.team, self.ticket.session_id, self.ticket.created_at.isoformat()
                )
            except Exception:
                capture_exception(additional_properties={"ticket_id": str(self.ticket.id)})

        # TODO: 2.2 — Search across custom content sources (help articles, docs, uploaded documents)
        # TODO: 2.3 — Semantic search across knowledge base using embeddings
        # TODO: 2.4 — Score and rank retrieved results, apply top-N cutoff

        if events or exceptions:
            context = _format_enhanced_context(self.conversation_text, events, exceptions)

        return context

    # -- Phase 3: Generate Response --

    def _generate_response(self) -> str:
        """Generate a reply using all gathered context."""
        assert self.refined_query is not None
        assert self.retrieved_context is not None

        # TODO: 3.2 — Apply custom Guidance rules (tone, behavior, response style)

        user_content = self._build_generation_prompt()

        parsed, completion = _llm_call_with_retry(
            self.client,
            messages=[
                {"role": "system", "content": GENERATE_RESPONSE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=SuggestedReplySchema,
            max_tokens=800,
        )

        reply_text = parsed.reply_text.strip()
        if not reply_text:
            raise ValueError("AI returned an empty response")

        usage = getattr(completion, "usage", None)
        if usage:
            logger.info(
                "AI suggestion generated",
                extra={
                    "ticket_id": str(self.ticket.id),
                    "input_tokens": getattr(usage, "prompt_tokens", 0),
                    "output_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
            )

        return reply_text

    def _build_generation_prompt(self) -> str:
        """Structure all context into the user message for response generation."""
        assert self.refined_query is not None
        assert self.retrieved_context is not None

        parts = [
            f"## Refined Query\n{self.refined_query.refined_query}",
            f"\n## Customer Intent\n{self.refined_query.intent_summary}",
            f"\n## Conversation & Context\n{self.retrieved_context}",
        ]
        return "\n".join(parts)

    # -- Phase 4: Validate Response --

    def _validate_response(self) -> ResponseValidationSchema:
        """Check the generated response for quality and groundedness."""
        assert self.generated_reply is not None
        assert self.retrieved_context is not None

        parts = [f"## Original Conversation\n{self.conversation_text}"]

        if self.retrieved_context != self.conversation_text:
            parts.append(f"\n\n## Retrieved Context\n{self.retrieved_context}")

        parts.append(f"\n\n## Generated Response\n{self.generated_reply}")
        validation_input = "".join(parts)

        parsed, _ = _llm_call_with_retry(
            self.client,
            messages=[
                {"role": "system", "content": VALIDATE_RESPONSE_SYSTEM_PROMPT},
                {"role": "user", "content": validation_input},
            ],
            response_format=ResponseValidationSchema,
        )
        return parsed


class NoMessagesError(Exception):
    """Raised when a ticket has no messages to generate a reply for."""

    pass


def suggest_reply(
    ticket: Ticket,
    team: Team,
    user_distinct_id: str,
) -> str:
    """
    Generate AI-suggested reply using the multi-phase RAG pipeline.

    Fetches non-private messages for the ticket, runs the pipeline:
    1. Refine query (safety + classification + optimization)
    2. Retrieve content (session events/exceptions + future sources)
    3. Generate response
    4. Validate response
    5. Retry from step 1 if validation fails (max 3 attempts)

    Returns the generated reply text.
    Raises NoMessagesError if ticket has no messages.
    Raises other exceptions on failure.
    """
    messages = list(
        Comment.objects.filter(
            team_id=team.id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
        )
        .exclude(item_context__is_private=True)
        .order_by("created_at")
    )

    if not messages:
        raise NoMessagesError("No messages in this ticket")

    pipeline = AISuggestPipeline(ticket, messages, team, user_distinct_id)
    reply_text = pipeline.run()

    Comment.objects.create(
        team_id=team.id,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=reply_text,
        item_context={"author_type": "AI", "is_private": True},
    )

    return reply_text
