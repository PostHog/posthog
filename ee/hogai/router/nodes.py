from collections.abc import Callable

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.messages import BaseMessage, ToolCall
from langchain_core.messages import HumanMessage as LangchainHumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from ee.hogai.router.prompts import router_system_prompt
from ee.hogai.utils import AssistantNode, AssistantState
from posthog.models.team.team import Team
from posthog.schema import HumanMessage, RouterMessage


@tool(parse_docstring=True)
def generate_trends_insight():
    """
    Trends insights enable users to plot data from people, events, and properties however they want. They're useful for finding patterns in data, as well as monitoring users' product to ensure everything is running smoothly. For example, using trends, users can analyze:
    - How product's most important metrics change over time.
    - Long-term patterns, or cycles in product's usage.
    - How a specific change affects usage.
    - The usage of different features side-by-side.
    - How the properties of events vary using aggregation (sum, average, etc).
    - Users can also visualize the same data points in a variety of ways.
    """
    return "trends"


@tool(parse_docstring=True)
def generate_funnel_insight():
    """
    For every flow in the user's product, more people will start it than complete it successfully. Funnels enable users to visualize their flows and understand where the friction points are so that they can improve them. Users can learn the following from funnels:
    - What are the conversion rates and how seasonality affects them.
    - Where people are getting stuck during their flow.
    - Who successful and unsuccessul users are.
    - The steps with the highest friction and time to convert.
    - The paths users take in a funnel.
    - If product changes are improving their funnel over time.
    """
    return "funnel"


class RouterNode(AssistantNode):
    def __init__(self, team: Team):
        super().__init__(team)
        self._tools: dict[str, Callable] = {
            "generate_trends_insight": generate_trends_insight,
            "generate_funnel_insight": generate_funnel_insight,
        }

    def run(self, state: AssistantState, config: RunnableConfig):
        model = self._model.bind_tools(self._tools.values(), tool_choice="required", parallel_tool_calls=False)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", router_system_prompt),
            ],
            template_format="mustache",
        ) + self._reconstruct_conversation(state)
        chain = prompt | model

        message: LangchainAIMessage = chain.invoke({"input": state.input}, config)
        tool_name = message.tool_calls[0]["name"]
        tool = self._tools[tool_name]()
        return {"messages": [RouterMessage(route=tool)]}

    def router(self, state: AssistantState):
        last_message = state["messages"][-1]
        if isinstance(last_message, RouterMessage):
            return last_message.route
        raise ValueError("Invalid route.")

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o-mini", temperature=0, streaming=True)

    def _reconstruct_conversation(self, state: AssistantState):
        history: list[BaseMessage] = []
        for message in state["messages"]:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content))
            elif isinstance(message, RouterMessage):
                tool_call: ToolCall = {
                    "name": message.route,
                    "args": {},
                }
                history.append(LangchainAIMessage(content="", tool_calls=[tool_call]))
        return history
