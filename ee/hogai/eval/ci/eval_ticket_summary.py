import re

import pytest

from autoevals.llm import LLMClassifier
from autoevals.partial import ScorerWithPartial
from braintrust import EvalCase, Score
from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
)

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.ticket.prompts import (
    SUPPORT_SUMMARIZER_SYSTEM_PROMPT,
    SUPPORT_SUMMARIZER_USER_PROMPT,
    SUPPORT_TICKET_TOPICS,
)
from ee.hogai.chat_agent.slash_commands.commands.ticket.transcript import (
    customer_turns,
    render_transcript,
    unverifiable_quotes,
)
from ee.hogai.llm import MaxChatAnthropic

from ..base import MaxPublicEval

VALID_TOPIC_KEYS = set(re.findall(r"^- ([\w-]+):", SUPPORT_TICKET_TOPICS, re.M))

TOPIC_LINE = re.compile(r"\*\*Topic:?\*\*:?\s*([\w-]+)")

QUOTED_SPAN = re.compile(r'"([^"\n]{6,})"')

CREDENTIAL_PATTERNS = [
    re.compile(r"base64-[A-Za-z0-9+/=_-]{12,}"),
    re.compile(r"\b(?:phc|phx|phs)_[A-Za-z0-9]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}"),
    re.compile(r"-b\s*'[^']*=[^']{12,}"),
]


def _to_messages(conversation: list[dict[str, str]]) -> list[HumanMessage | AssistantMessage]:
    built: list[HumanMessage | AssistantMessage] = []
    for message in conversation:
        if message["role"] == "human":
            built.append(HumanMessage(content=message["content"]))
        else:
            built.append(AssistantMessage(content=message["content"]))
    return built


class TicketSummaryQuality(LLMClassifier):
    """Judge whether the summary records the customer's side of the conversation."""

    def __init__(self, **kwargs):
        super().__init__(
            name="ticket_summary_quality",
            prompt_template="""A support engineer will read this ticket description without seeing the
conversation it came from. Judge whether it serves them.

It should:
1. Use only these section labels, in this order, omitting any with nothing to report:
   **Reported issue:**, **Details provided:**, **Checked by the customer:**, **Not yet answered:**, **Topic:**
2. Open with a verbatim quote of how the customer described the problem
3. Record what the customer said, not what PostHog AI found, suggested, or concluded
4. Carry no diagnosis of its own, and repeat no PostHog AI diagnosis as if it were established
5. Write in third person, calling them "the customer"
6. Put one line per item under the list sections, with no narration between them
7. Stay proportionate, so a long conversation about a small issue gets a short summary

Generated summary:
<summary>
{{output}}
</summary>

What this summary should contain:
{{expected}}

Choose one:
- pass: right sections, leads with the customer's words, records their side, no invented diagnosis
- fail: narrates what PostHog AI did, carries its own or PostHog AI's diagnosis, wrong or missing
  sections, first person, pads sections it has nothing to report, or misses the actual issue""",
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-4.1",
            **kwargs,
        )


class QuoteFidelity(ScorerWithPartial):
    """Share of quoted spans that a single customer message contains verbatim.

    Scored on raw model output rather than the verified summary, so prompt drift stays visible
    even though strip_unverifiable_quotes would remove the marks in production.
    """

    def _run_eval_sync(self, output, expected, **kwargs):
        turns = customer_turns(_to_messages(kwargs["input"]))
        spans = QUOTED_SPAN.findall(output or "")
        if not spans:
            return Score(name=self._name(), score=None, metadata={"reason": "no quoted spans"})
        bad = unverifiable_quotes(output, turns)
        return Score(
            name=self._name(),
            score=(len(spans) - len(bad)) / len(spans),
            metadata={"quotes": len(spans), "unverifiable": bad},
        )


class NoCredentialLeak(ScorerWithPartial):
    """A summary must never carry a credential into the ticket, however the customer pasted it."""

    def _run_eval_sync(self, output, expected, **kwargs):
        found = [match.group(0)[:12] for pattern in CREDENTIAL_PATTERNS for match in pattern.finditer(output or "")]
        return Score(name=self._name(), score=0.0 if found else 1.0, metadata={"matched": found})


class ResolvableTopic(ScorerWithPartial):
    """The Topic line must resolve to a real key, or be absent so the support form can fall back."""

    def _run_eval_sync(self, output, expected, **kwargs):
        match = TOPIC_LINE.search(output or "")
        if match is None:
            return Score(name=self._name(), score=None, metadata={"reason": "no topic line"})
        key = match.group(1)
        return Score(name=self._name(), score=1.0 if key in VALID_TOPIC_KEYS else 0.0, metadata={"key": key})


@pytest.fixture
def call_summarizer(demo_org_team_user):
    async def callable(conversation: list[dict[str, str]]) -> str:
        transcript = render_transcript(_to_messages(conversation))
        messages_list: list[SystemMessage | LangchainHumanMessage] = [
            SystemMessage(content=SUPPORT_SUMMARIZER_SYSTEM_PROMPT),
            LangchainHumanMessage(
                content=f"<transcript>\n{transcript}\n</transcript>\n\n{SUPPORT_SUMMARIZER_USER_PROMPT}"
            ),
        ]
        model = MaxChatAnthropic(
            model="claude-sonnet-5",
            streaming=False,
            user=demo_org_team_user[2],
            team=demo_org_team_user[1],
            max_tokens=2048,
            thinking={"type": "disabled"},
            billable=False,
            inject_context=False,
        )
        response = await model.ainvoke(messages_list)
        content = response.content
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        return content

    return callable


@pytest.mark.django_db
async def eval_ticket_summary(call_summarizer, pytestconfig):
    await MaxPublicEval(
        experiment_name="ticket_summary",
        task=call_summarizer,
        scores=[TicketSummaryQuality(), QuoteFidelity(), NoCredentialLeak(), ResolvableTopic()],
        data=[
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "Id like to submit a feature request for cost in the AI observability overview to be customisable to other currencies than only USD",
                    },
                    {
                        "role": "assistant",
                        "content": "The best way to get this in front of the team is the `/ticket` command right here. You can also post it at posthog.com/questions so others can upvote it.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A short summary quoting the customer's request for non-USD currency in the AI observability overview. Nothing about PostHog AI directing them to /ticket or posthog.com/questions, which is not the issue. Topic llm-analytics.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "I accidently merged a PR that was setup on inbox that was actually implemented elsewhere - I've manually reversed it. How do I appeal the cost",
                    },
                    {
                        "role": "assistant",
                        "content": "That relates to Signals, where you are charged per PR. If a PR does not meet the bar it can be refunded, you just need to contact support.",
                    },
                    {
                        "role": "human",
                        "content": "/ticket I recently enabled inbox in my environment and self-drive. I accidenty connected it to my issue tracker and then an issue was merged that was actually implemented elsewhere. I reversed the merge. I wanted to ask if I could request a refund on the cost of the PR.",
                    },
                ],
                expected="A refund request for a Signals PR charge, quoting the customer. Their spellings accidently and accidenty must survive exactly wherever quoted, and no quote may mix words from their two separate messages. Topic signals or billing.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "My managed reverse proxy ph.example-shop.io is now Erroring. The certificate activity says “Certificate not yet ready, status: pending_validation.” DNS CNAME, CAA records and HTTP-01 validation previously passed. I have already recreated the managed proxy once, but certificate validation remains stuck.",
                    },
                    {
                        "role": "assistant",
                        "content": "I cannot act on PostHog infrastructure directly. Worth checking your DNS record is set to DNS only rather than proxied, since that breaks HTTP-01 validation.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The proxy domain, the pending_validation certificate status quoted from the customer, that CNAME, CAA and HTTP-01 previously passed, and that they already recreated the proxy once. PostHog AI's DNS only suggestion must not appear as something the customer said or checked. Topic platform_addons.",
            ),
            EvalCase(
                input=[
                    {"role": "human", "content": 'help me finding this "Data management then Events"'},
                    {
                        "role": "assistant",
                        "content": "You can find it at Data management in the left sidebar, which opens the Events tab by default.",
                    },
                    {
                        "role": "human",
                        "content": "I am looking at the Session replay and the latest recording was me and it show show a Belgian flag and not Dutch (Netherlands). The two countries are not the same even though many people make that mistake. fix it please.",
                    },
                    {
                        "role": "assistant",
                        "content": "This is a GeoIP detection issue. Either a VPN is involved, or the GeoIP database has your IP block mapped incorrectly.",
                    },
                    {
                        "role": "human",
                        "content": "/ticket I am seeing Belgian flags instead of the Dutch, when I am testing my website example-shop.nl. I am not using any proxies and I expected that the recording will be based on my IP address in Utrecht. I am wondering if the ret of the flags are all random.",
                    },
                ],
                expected="Only the wrong country flag on session recordings. The opening turn about finding Data management is not the issue and should not appear. The customer's show show and ret must survive verbatim wherever quoted. Topic session_replay.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": '"This source syncs using Acme API version v1, which the vendor has deprecated. Contact PostHog support to migrate this source to version v2 before syncs stop working."\n\ncontacting to get this migrated!',
                    },
                    {
                        "role": "assistant",
                        "content": "The best way is in-app support, or the `/ticket` command right here in this chat.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A request to migrate a warehouse source off the deprecated vendor API v1 to v2, quoting the product warning the customer pasted. The same fact must not be restated as three separate detail lines. Topic data_warehouse.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "what are the assignee ids by name? trying to create a workflow for when something is assigned to sam or me?",
                    },
                    {
                        "role": "assistant",
                        "content": "Found them in the assignment logs: Sam is 100201 and you are 100202.",
                    },
                    {
                        "role": "human",
                        "content": "12 minutes ago\tERROR\t\n09fe0042\nWorkflow encountered an error: undefined at Update ticket to New from Resolved. Triggered by Event: $conversation_message_received\n\nwhat does this mean?",
                    },
                    {
                        "role": "assistant",
                        "content": "It means the workflow step is making an authenticated call back into PostHog but your project has no secret API token configured. This may be something PostHog needs to configure, or it could be a bug in workflows.",
                    },
                    {
                        "role": "human",
                        "content": "are you aware of any spot I should configure this? I searched and couldn't find it",
                    },
                    {"role": "assistant", "content": "I cannot find a documented UI setting for it."},
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The workflow error text quoted from the customer, the workflow id 09fe0042, and that they searched for the setting and could not find it. It must not assert this is a bug in workflows, since only PostHog AI speculated that. Topic workflows.",
            ),
            EvalCase(
                input=[
                    {"role": "human", "content": "bug report - https://example.com/share/abc123"},
                    {
                        "role": "assistant",
                        "content": "I cannot open external links. Could you describe the bug or paste any error messages?",
                    },
                    {"role": "human", "content": "/ticket"},
                    {
                        "role": "assistant",
                        "content": "PostHog AI Support Ticket Summary:\n\n**Issue:** The user reported a bug via a link and asked PostHog AI to submit it. No description of the actual bug was provided.\n\n**Status:** PostHog AI is unable to access external links and asked the user to describe the bug in text.",
                    },
                    {"role": "human", "content": 'bug - shaking ui with high frequency on "Overview" tab'},
                    {
                        "role": "assistant",
                        "content": "Got it. Run `/ticket` again and it will include this context.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The shaking UI on the Overview tab, quoted from the customer. The earlier PostHog AI Support Ticket Summary in the conversation is PostHog AI's own output and must not be treated as something the customer said. Any gaps listed should be ones actually left open in the conversation, not a generic triage checklist.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "the limit was reached few days back and right now we added the credit card and extended the limit. so will we get the event from thoses days right now?",
                    },
                    {
                        "role": "assistant",
                        "content": "No. Events that arrive while a billing limit is reached are permanently dropped at ingestion and are unrecoverable, even after raising the limit.",
                    },
                    {"role": "human", "content": "i would like to send a support mail to them"},
                    {
                        "role": "assistant",
                        "content": "Use the `/ticket` command here and it will create one with the context.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The customer asking whether events dropped during a billing limit can be recovered after adding a card. It must record that the customer was already told the events are permanently dropped, since support needs that before replying. Topic billing.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "me ayudas a poner un tiket? en este momento  no esta funcionando source, arroja unicamente error de servidor",
                    },
                    {
                        "role": "assistant",
                        "content": "Claro. Para crear un ticket, usa el comando `/ticket` en este chat.",
                    },
                    {
                        "role": "human",
                        "content": "al entrar a la pagina y arroja unicamente error de servidor: Load failed: A server error ocurred",
                    },
                    {
                        "role": "assistant",
                        "content": "Perfecto, escribe `/ticket` y se creara con esta informacion.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A server error when loading the data warehouse Sources page. The error text must be quoted with the customer's own spelling ocurred, not corrected to occurred. Topic data_warehouse.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "For identify I'm using a token with phs_ schema and when I use it for support I get a 403. ask me questions to triage the issue",
                    },
                    {
                        "role": "assistant",
                        "content": "The support widget uses HMAC-SHA256 for identity verification. A 403 usually means signature verification failed. How are you passing the identity?",
                    },
                    {
                        "role": "human",
                        "content": "I'm setting the identity with .setIdentity. the HMAC is generated on the server. I'm using a token with featureflag read scope because the one in the widget settings cannot be generated. yes they match. see\n\ncurl 'https://demo.example.com/api/conversations/v1/widget/message' -H 'content-type: application/json' -b '_ga=GA1.1.2052330030.1781297172; app-auth-token=base64-eyJhY2Nlc3NfdG9rZW4iOiJleUpoYkdjaU9pSklVekkxTmlJc0k'",
                    },
                    {
                        "role": "assistant",
                        "content": "The HMAC must be signed with the project's secret token, not a scoped API key.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A 403 from support widget identity verification, that the HMAC is generated server side, and that the customer used a featureflag-read-scoped token because the widget settings one could not be generated. The pasted cookie header must be described rather than reproduced, and no token value may appear anywhere.",
            ),
        ],
        pytestconfig=pytestconfig,
    )
