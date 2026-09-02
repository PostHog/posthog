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
)
from ee.hogai.chat_agent.slash_commands.commands.ticket.transcript import (
    customer_turns,
    quoted_spans,
    render_transcript,
    unverifiable_quotes,
)
from ee.hogai.llm import MaxChatAnthropic

from ..base import MaxPublicEval


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
            prompt_template="""A support engineer is opening this ticket for the first time, and will
read the conversation it came from afterwards. Judge whether this orients them accurately.

It should:
1. Use only these section labels, in this order, omitting any with nothing to report:
   **Reported issue:**, **Details provided:**, **Checked by the customer:**
2. Open with a verbatim quote of how the customer described the problem
3. Record what the customer said, not what PostHog AI found, suggested, asked or concluded. Its
   answer to a question the customer actually asked may appear, but only as "the customer was told"
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
- fail: narrates what PostHog AI did, carries its own or PostHog AI's diagnosis, lists steps for
  anyone to take, wrong or missing sections, first person, pads sections it has nothing to report,
  or misses the actual issue""",
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
        spans = quoted_spans(output or "")
        if not spans:
            return Score(name=self._name(), score=None, metadata={"reason": "no quoted spans"})
        bad = unverifiable_quotes(output, turns)
        return Score(
            name=self._name(),
            score=(len(spans) - len(bad)) / len(spans),
            metadata={"quotes": len(spans), "unverifiable": bad},
        )


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
        scores=[TicketSummaryQuality(), QuoteFidelity()],
        data=[
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "can you add a way to show the spend column in something other than dollars? our finance team works in euros",
                    },
                    {
                        "role": "assistant",
                        "content": "The best way to get this in front of the team is the `/ticket` command right here. You can also post it publicly so others can upvote it.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A short summary quoting the customer's request to show spend in a currency other than dollars. Nothing about PostHog AI pointing them at /ticket or at posting publicly, which is not the issue.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "I mistakenly approved a change that was allready done on another branch, and I rolled it back myself. can the charge be looked at",
                    },
                    {
                        "role": "assistant",
                        "content": "That relates to Signals, where you are charged per change. If one does not meet the bar it can be refunded, you just need to contact support.",
                    },
                    {
                        "role": "human",
                        "content": "/ticket I switched on the inbox and self drive last week. I mistakinly pointed it at our tracker and a change got approved that was allready done elsewhere. I rolled it back. I would like to ask about getting the charge refunded.",
                    },
                ],
                expected="A refund request for a per-change Signals charge, quoting the customer. Their spellings mistakenly, mistakinly and allready must survive exactly wherever quoted, and no quote may mix words from their two separate messages.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "our managed reverse proxy proxy.example.com has started failing. the certificate panel says \u201cCertificate not ready yet, state: awaiting_validation.\u201d the CNAME and CAA entries and the HTTP-01 check all passed before. I tore the proxy down and set it up again once already and validation is still stuck.",
                    },
                    {
                        "role": "assistant",
                        "content": "I cannot act on PostHog infrastructure directly. Worth checking your DNS record is set to DNS only rather than proxied, since that breaks the HTTP-01 check.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The proxy hostname, the awaiting_validation certificate state quoted from the customer, that CNAME, CAA and HTTP-01 passed before, and that they already rebuilt the proxy once. PostHog AI's DNS only suggestion must not appear as something the customer said or checked.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": 'where do I find the thing you mentioned, "Data management and then Events"',
                    },
                    {
                        "role": "assistant",
                        "content": "It is under Data management in the left sidebar, which opens the Events tab by default.",
                    },
                    {
                        "role": "human",
                        "content": "im on the Session replay page and the newest recording is mine and it shows shows an Austrian flag rather than German. those are different countries even if people mix them up. please sort it out.",
                    },
                    {
                        "role": "assistant",
                        "content": "This is a GeoIP detection issue. Either a VPN is in the path, or the GeoIP database has your IP block mapped incorrectly.",
                    },
                    {
                        "role": "human",
                        "content": "/ticket hi support, im getting Austrian flags where I expect German ones, testing on example.com. no proxy or vpn here and I assumed it reads my IP in Hamburg. why is the recording list showing the wrong one. makes me wonder if the rst of the flags are guesswork too.",
                    },
                ],
                expected="Only the wrong country flag on session recordings. The opening turn about finding Data management is not the issue and should not appear. The customer's im, shows shows and rst must survive verbatim wherever quoted.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": '"This connection uses Widgetly API v1, which the provider no longer supports. Contact PostHog support to move it to v2 before syncing halts."\n\nreaching out to get that moved!',
                    },
                    {
                        "role": "assistant",
                        "content": "The best route is in-app support, or the `/ticket` command right here in this chat.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A request to move a warehouse connection off the unsupported vendor API v1 to v2, quoting the product warning the customer pasted. The same fact must not be restated as three separate detail lines.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "how do I get the numeric ids for people by name? building an automation for when work lands on jo or on me",
                    },
                    {
                        "role": "assistant",
                        "content": "Pulled them from the assignment history: Jo is 100201 and you are 100202.",
                    },
                    {
                        "role": "human",
                        "content": "8 minutes ago\tERROR\t\n7bd10099\nAutomation failed: undefined at Move ticket to Open from Closed. Fired by Event: $conversation_message_received\n\nwhat is this telling me?",
                    },
                    {
                        "role": "assistant",
                        "content": "It means the automation step is making an authenticated call back into PostHog but your project has no secret API token set. This may be something PostHog needs to configure, or it could be a bug in automations.",
                    },
                    {
                        "role": "human",
                        "content": "any idea where I would set that? I had a look and came up empty",
                    },
                    {"role": "assistant", "content": "I cannot find a documented setting for it."},
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The automation error text quoted from the customer, the id 7bd10099, and that they looked for the setting and came up empty. It must not assert this is a bug in automations, since only PostHog AI speculated that.",
            ),
            EvalCase(
                input=[
                    {"role": "human", "content": "bug report - https://example.net/clip/7f2a91"},
                    {
                        "role": "assistant",
                        "content": "I cannot open external links. Could you describe the bug, or paste any error text?",
                    },
                    {"role": "human", "content": "/ticket"},
                    {
                        "role": "assistant",
                        "content": "PostHog AI Support Ticket Summary:\n\n**Issue:** The user reported a bug via a link and asked PostHog AI to pass it on. No description of the actual bug was given.\n\n**Status:** PostHog AI cannot open external links and asked the user to describe the bug in text.",
                    },
                    {"role": "human", "content": 'bug - panel jitters rapidly on the "Summary" tab'},
                    {
                        "role": "assistant",
                        "content": "Got it. Run `/ticket` again and it will include this context.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The jittering panel on the Summary tab, quoted from the customer. The earlier PostHog AI Support Ticket Summary in the conversation is PostHog AI's own output and must not be treated as something the customer said.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "we hit the cap a couple of days ago and just now put a card on and raised it. do the events from those days come through now?",
                    },
                    {
                        "role": "assistant",
                        "content": "No. Events arriving while a billing limit is reached are dropped at ingestion and cannot be recovered, even after the limit is raised.",
                    },
                    {"role": "human", "content": "id like to email support about it"},
                    {
                        "role": "assistant",
                        "content": "Use the `/ticket` command here and it will create one with the context.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="The customer asking whether events dropped while a billing limit was reached arrive after adding a card. It must record that the customer was already told those events cannot be recovered, since support needs that before replying.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "puedes ayudarme a abrir un tikete? ahora mismo la fuente no carga, solo muestra un error del servidor",
                    },
                    {
                        "role": "assistant",
                        "content": "Claro. Para crear un ticket, usa el comando `/ticket` en este chat.",
                    },
                    {
                        "role": "human",
                        "content": "al abrir la pagina solo sale error del servidor: Load failed: A server error occured",
                    },
                    {
                        "role": "assistant",
                        "content": "Entendido, escribe `/ticket` y se creara con esta informacion.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A server error when loading the data warehouse sources page. The error text must be quoted with the customer's own spelling occured, not corrected to occurred.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "for identify I am using a token with the phs_ shape and I get a 403 when I use it for support. ask me questions to narrow it down",
                    },
                    {
                        "role": "assistant",
                        "content": "The support widget verifies identity with HMAC-SHA256. A 403 usually means signature verification failed. How are you passing the identity?",
                    },
                    {
                        "role": "human",
                        "content": "I call .setIdentity on the client and the HMAC comes from our backend. the token I used has featureflag read scope, since the one the widget settings page offers cannot be created. they line up, see\n\ncurl 'https://staging.example.com/api/conversations/v1/widget/message' -H 'content-type: application/json' -b '_ga=GA1.1.0000000000.0000000000; app-auth-token=base64-ZmFrZS1ldmFsLXRva2VuLXZhbHVlLWRvLW5vdC11c2U'",
                    },
                    {
                        "role": "assistant",
                        "content": "The HMAC has to be signed with the project's secret token, not a scoped API key.",
                    },
                    {"role": "human", "content": "/ticket"},
                ],
                expected="A 403 from support widget identity verification, that the HMAC is generated on their backend, and that they used a featureflag-read-scoped token because the widget settings one could not be created. The request they pasted is supporting detail, not the issue itself.",
            ),
        ],
        pytestconfig=pytestconfig,
    )
