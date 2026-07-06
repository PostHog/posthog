from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from products.customer_analytics.backend.facade.max_tools import UpsertAccountNotebookTool, UpsertAccountTool

from ee.hogai.chat_agent.executables import ChatAgentExecutable, ChatAgentToolsExecutable
from ee.hogai.tools.todo_write import TodoWriteExample

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


CUSTOMER_ANALYTICS_MODE_DESCRIPTION = (
    "Specialized mode for managing customer accounts. An account represents a customer organization. "
    "Use this mode to create and update accounts, assign customer-success roles (CSM, account "
    "executive, account owner), set external-system identifiers and tags, and save and update notes "
    "(call recaps, meeting summaries, investigation recaps) on an account. "
    "When the user asks about an account's usage, volume, spikes, growth, cost, or spend, they mean "
    "the account's CONSUMPTION of PostHog as a product — events ingested, data-warehouse rows synced, "
    "recordings, feature-flag requests, exceptions, MRR, spend — which lives in warehouse-synced billing "
    "data, surfaced by the account's saved Usage and Spend insights (and the Usage/Spend tabs in the "
    "Accounts list). This is the DEFAULT for usage questions: look up the account, read the relevant "
    "saved insight to get its warehouse query, then switch_mode to SQL and adapt that query scoped to the "
    "account. Do NOT answer a usage or spend question by counting the account's events — the event stream "
    "measures the people at the account interacting with the product (engagement), not the account's "
    "product consumption. Only analyze the account's events when the user explicitly asks about behavior "
    "or activity (what its people do in the product), reading the account first then switching to product "
    "analytics or SQL. "
    "For a quick 'show me usage' ask, point users to the account's Usage tab in the Accounts list rather "
    "than building a new insight. "
    "When you give the user a link to an account, link to that specific account so it opens directly, not "
    "to the bare accounts list. "
    "When the user investigates a single account across several turns — follow-up questions or digging "
    "into an issue — offer once to capture the investigation as a note: a timeline of what was checked "
    "and what you found, saved with upsert_account_notebook. If they decline, don't ask again. "
    "If an account is not connected to analytics yet, ask the user to finish connecting it in the "
    "Customer analytics > Accounts settings. "
    "Speak to users in terms of the account and its data; keep the underlying mechanics out of your responses."
)


POSITIVE_EXAMPLE_ASSIGN_ROLE = """
User: Make Jane the CSM for Acme Corp
Assistant: Let me find the Acme Corp account first.
*Uses list_data with the account kind to find the account's id*
Assistant: Found it. I'll assign Jane as the CSM.
*Uses the upsert_account tool with action=update, account_id=<uuid>, properties={csm: {id, email}}*
""".strip()

POSITIVE_EXAMPLE_ASSIGN_ROLE_REASONING = """
1. The account must be looked up by its id before it can be updated.
2. Assigning a single role is a one-step task, so no todo list is needed.
3. The CSM assignment requires the assignee's user id and email.
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_USAGE = """
User: How has Acme Corp's usage been lately?
Assistant: Let me open Acme Corp's usage.
*Opens the Acme Corp account's Usage tab in the Accounts list*
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_USAGE_REASONING = """
1. Each account's usage already lives in its Usage tab in the Accounts list, so the assistant opens that directly instead of building a new insight.
2. Surfacing the existing view is faster and consistent with the rest of the product.
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_USAGE_SPIKE = """
User: Did Acme Corp have a usage spike recently?
Assistant: Let me check Acme Corp's consumption.
*Creates a todo list:*
1. Look up the Acme Corp account (read_data with the account kind)
2. Read the account's saved Usage insight to get its warehouse query
3. Switch to SQL mode
4. Adapt that query scoped to Acme Corp and compare the recent window to the prior period
5. Identify which consumption metric spiked (events ingested, rows synced, recordings, …) and when
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_USAGE_SPIKE_REASONING = """
1. "Usage spike" is a consumption question — it's about how much of PostHog the account consumes (events ingested, rows synced), which lives in the warehouse billing data, not in the account's event stream (that would measure the account's people using the product).
2. Reading the saved Usage insight first gives the exact warehouse query to adapt, so the analysis stays consistent with the Usage tab instead of being rebuilt from scratch.
3. The analysis itself runs in SQL mode after the switch, scoped to the account, comparing periods to locate the spike.
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS = """
User: Acme Corp's spend jumped last month — help me understand why.
Assistant: Let me dig into what drove Acme Corp's spend.
*Creates a todo list:*
1. Look up the Acme Corp account (read_data with the account kind)
2. Read the account's saved Spend insight (and Usage insight) to get their warehouse queries
3. Switch to SQL mode
4. Adapt those queries scoped to Acme Corp, comparing last month to the prior period by product
5. Identify which product's consumption and cost grew and summarize the likely driver
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS_REASONING = """
1. Spend is consumption-based, so the answer ties to which products' usage grew — both live in the warehouse billing data behind the Spend and Usage insights, not in the account's event stream.
2. Reading those saved insights first gives the warehouse queries to adapt, keeping the analysis consistent with the Spend/Usage tabs rather than rebuilt from scratch.
3. The account is looked up first, then the period-over-period comparison runs in SQL mode after the switch — something the built-in tabs don't provide on their own.
""".strip()

POSITIVE_EXAMPLE_SAVE_NOTE = """
User: Save a recap on Acme Corp from today's call — they want SSO by Q3 and flagged slow dashboards.
Assistant: Let me find the Acme Corp account first.
*Uses list_data with the account kind to get the account's id*
Assistant: Saving the recap to Acme Corp's notes.
*Uses the upsert_account_notebook tool with action=create, account_id=<uuid>, title="Call recap", content="<markdown>"*
""".strip()

POSITIVE_EXAMPLE_SAVE_NOTE_REASONING = """
1. A note attaches to a specific account, so its id must be resolved before the note can be created.
2. Saving one note is a single step once the id is known, so no todo list is needed.
3. The recap is written as Markdown in the note body.
""".strip()

POSITIVE_EXAMPLE_DEEP_DIVE = """
User: (several questions into Acme Corp's activity drop) ...and how does that compare to last quarter?
Assistant: We're a few questions into Acme Corp's situation — want me to keep a recap of this investigation in the account's notes? I'd capture a timeline of what we've looked at and what we found.
User: Yes, please.
Assistant: Will do — I'll answer this, then save the recap.
*Answers the question, then uses the upsert_account_notebook tool with action=create, account_id=<uuid>, title="Activity drop investigation", content="<markdown timeline: questions explored, what was checked, findings>"*
""".strip()

POSITIVE_EXAMPLE_DEEP_DIVE_REASONING = """
1. Several turns focused on one account signal a deep-dive — the moment to offer to capture it, once, rather than on every turn.
2. The recap is post-hoc and opt-in: on agreement the assistant writes a single timeline note with upsert_account_notebook; if the user declines, it just continues.
3. Saving the recap is one step, so it needs no todo list of its own — though the investigation it summarizes may itself be todo-tracked.
""".strip()

POSITIVE_EXAMPLE_UPDATE_NOTE = """
User: Add to that recap — they also asked about SSO pricing.
Assistant: I'll update the recap.
*Uses the upsert_account_notebook tool with action=update, notebook_short_id=<from when the note was created>, content="<full updated markdown>"*
""".strip()

POSITIVE_EXAMPLE_UPDATE_NOTE_REASONING = """
1. Updating reuses the note's short_id from when it was created, so no fresh account lookup is needed.
2. content REPLACES the body, so the assistant sends the full updated note, not just the new line.
3. It's a single step, so no todo list is needed.
""".strip()


class CustomerAnalyticsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(example=POSITIVE_EXAMPLE_ASSIGN_ROLE, reasoning=POSITIVE_EXAMPLE_ASSIGN_ROLE_REASONING),
        TodoWriteExample(example=POSITIVE_EXAMPLE_ACCOUNT_USAGE, reasoning=POSITIVE_EXAMPLE_ACCOUNT_USAGE_REASONING),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_ACCOUNT_USAGE_SPIKE, reasoning=POSITIVE_EXAMPLE_ACCOUNT_USAGE_SPIKE_REASONING
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS, reasoning=POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS_REASONING
        ),
        TodoWriteExample(example=POSITIVE_EXAMPLE_SAVE_NOTE, reasoning=POSITIVE_EXAMPLE_SAVE_NOTE_REASONING),
        TodoWriteExample(example=POSITIVE_EXAMPLE_DEEP_DIVE, reasoning=POSITIVE_EXAMPLE_DEEP_DIVE_REASONING),
        TodoWriteExample(example=POSITIVE_EXAMPLE_UPDATE_NOTE, reasoning=POSITIVE_EXAMPLE_UPDATE_NOTE_REASONING),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [UpsertAccountTool, UpsertAccountNotebookTool]


customer_analytics_agent = AgentModeDefinition(
    mode=AgentMode.CUSTOMER_ANALYTICS,
    mode_description=CUSTOMER_ANALYTICS_MODE_DESCRIPTION,
    toolkit_class=CustomerAnalyticsAgentToolkit,
    node_class=ChatAgentExecutable,
    tools_node_class=ChatAgentToolsExecutable,
)
