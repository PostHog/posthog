from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from products.customer_analytics.backend.max_tools import UpsertAccountTool

from ee.hogai.chat_agent.executables import ChatAgentExecutable, ChatAgentToolsExecutable
from ee.hogai.tools.todo_write import TodoWriteExample

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


CUSTOMER_ANALYTICS_MODE_DESCRIPTION = (
    "Specialized mode for managing customer accounts. An account represents a customer organization. "
    "Use this mode to create and update accounts, assign customer-success roles (CSM, account "
    "executive, account owner), and set external-system identifiers and tags. "
    "Each account's usage is already available in the Accounts list — in the expanded row's Usage tab — "
    "so point users there rather than building a new insight for it. "
    "For other questions about an account's activity or behavior, first look up the account — reading "
    "it gives you the context needed to analyze it — then switch_mode to product analytics or SQL to "
    "run the analysis for that account. "
    "If an account is not connected to analytics yet, ask the user to finish connecting it in the "
    "Customer analytics > Accounts settings. "
    "Speak to users in terms of the account and its data; keep the underlying mechanics out of your responses."
)


POSITIVE_EXAMPLE_ASSIGN_ROLE = """
User: Make Jane the CSM for Acme Corp
Assistant: Let me find the Acme Corp account first.
*Uses the search tool (or list_data with the account kind) to find the account's id*
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

POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS = """
User: Acme Corp had an MRR spike last month — help me understand why.
Assistant: Let me dig into what drove Acme Corp's spike.
*Creates a todo list:*
1. Look up the Acme Corp account (read_data with the account kind)
2. Switch to product analytics (or SQL) mode
3. Build an insight — branching off the account's existing usage view — comparing usage by product last month vs the prior period
4. Identify which products grew and summarize the likely driver of the spike
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS_REASONING = """
1. This is a "why" question, not a "what" — the Usage tab shows the account's usage, but here the user wants the explanation behind an MRR change.
2. MRR is usage-based, so the answer ties to which products' usage grew; that needs a period-over-period comparison the built-in tabs don't provide.
3. The account is looked up first, then the analysis runs after switching to product analytics or SQL — reusing the existing usage view as a starting point rather than building from scratch.
""".strip()


class CustomerAnalyticsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(example=POSITIVE_EXAMPLE_ASSIGN_ROLE, reasoning=POSITIVE_EXAMPLE_ASSIGN_ROLE_REASONING),
        TodoWriteExample(example=POSITIVE_EXAMPLE_ACCOUNT_USAGE, reasoning=POSITIVE_EXAMPLE_ACCOUNT_USAGE_REASONING),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS, reasoning=POSITIVE_EXAMPLE_ACCOUNT_ANALYTICS_REASONING
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [UpsertAccountTool]


customer_analytics_agent = AgentModeDefinition(
    mode=AgentMode.CUSTOMER_ANALYTICS,
    mode_description=CUSTOMER_ANALYTICS_MODE_DESCRIPTION,
    toolkit_class=CustomerAnalyticsAgentToolkit,
    node_class=ChatAgentExecutable,
    tools_node_class=ChatAgentToolsExecutable,
)
