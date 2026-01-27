# PostHog AI

This directory contains the PostHog AI platform and its core features.

[Getting started with PostHog AI.](https://posthog.slack.com/docs/TSS5W8YQZ/F08UU1LJFUP)

## For product teams: MaxTool

Add new PostHog AI capabilities using the MaxTool API. You can allow our AI agent to do anything in your product: both perform backend actions and control the UI. A tool can itself involve an LLM call based on a prompt tailored to the tool's task, using arguments provided to the tool by the root node + context passed from the frontend.

To implement a MaxTool you first define it in the backend, then you mount it in the frontend. The backend definition contains the tool's metadata for the LLM (what is it, how to use it, when to use it, what arguments it takes) and its actual implementation. The frontend React mount point makes the tool available - i.e. the tool can only be called when the UI being automated is present.

You'll need to set [env vars](https://posthog.slack.com/docs/TSS5W8YQZ/F08UU1LJFUP) in order to hack on this – just ask in #team-posthog-ai to get those API keys.

### Defining

1. Create the `max_tools.py` file for your product, if it doesn't exist already: `products/<your product>/backend/max_tools.py`. `max_tools.py` files following this convention are automatically discovered and loaded by the system.

2. In your `max_tools.py`, define a new tool class inheriting from `MaxTool`:

   ```python
   from pydantic import BaseModel, Field

   from ee.hogai.llm import MaxChatOpenAI
   from ee.hogai.tool import MaxTool


   # Define your tool's arguments schema
   class YourToolArgs(BaseModel):
       parameter_name: str = Field(description="Description of the parameter")


   class YourToolOutput(BaseModel):
       result_data: int


   class YourTool(MaxTool):
       name: str = "your_tool_name"  # Must match a value in AssistantTool enum
       description: str = "What this tool does"
       context_prompt_template: str = "Context about the tool state: {context_var}"
       args_schema: type[BaseModel] = YourToolArgs

       async def _arun_impl(self, parameter_name: str) -> tuple[str, YourToolOutput]:
           # Implement tool logic here
           # Access context with self.context (must have context_var from template)
           # If you use Django's ORM, ensure you utilize its asynchronous capabilities.

           # Optional: Use LLM to process inputs or generate structured outputs
           model = MaxChatOpenAI(model="gpt-4o", temperature=0.2).with_structured_output(YourToolOutput).with_retry()

           response = model.ainvoke({"question": "What is PostHog?"})

           # Process and return results as (message, structured_data)
           return "Tool execution completed", response
   ```

3. Add your tool name to the `AssistantTool` union in `frontend/src/queries/schema/schema-assistant-messages.ts`, then run `pnpm schema:build`.

4. Define tool metadata in `TOOL_DEFINITIONS` in `frontend/src/scenes/max/max-constants.tsx`:

   ```tsx
   export const TOOL_DEFINITIONS: ... = {
       // ... existing tools ...
       your_tool_name: {
           name: 'Do something',
           description: 'Do something to blah blah',
           product: Scene.YourProduct, // or null for the rare global tool
           flag: FEATURE_FLAGS.YOUR_FLAG, // optional indication that this is flagged
       },
   }
   ```

For an example, see `ee/hogai/tools`:

- `execute_sql` – SQL generation and execution.
- `upsert_dashboard` – creating and editing dashboards.

### Mounting

Use the `MaxTool` component to wrap UI elements that can benefit from AI assistance:

```tsx
import { MaxTool } from 'scenes/max/MaxTool'

function YourComponent() {
  return (
    <MaxTool
      name="your_tool_name" // Must match backend tool name - enforced by the AssistantTool enum
      displayName="Human-friendly name"
      context={{
        // Context data passed to backend - can be empty if there truly is no context
        context_var: relevantData,
      }}
      callback={(toolOutput) => {
        // Handle structured output from tool
        updateUIWithToolResults(toolOutput)
      }}
      initialMaxPrompt="Optional initial prompt for Max"
      onMaxOpen={() => {
        // Optional actions when Max panel opens
      }}
    >
      {/* Your UI component that will have Max assistant */}
      <YourUIComponent />
    </MaxTool>
  )
}
```

When a tool is mounted, it automatically gets shown as available in the scene UI and Max itself, using `TOOL_DEFINITIONS` metadata to help the user understand the capability.

For an example, see `frontend/src/scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed.tsx`, which mounts the `search_session_recordings` tool.

### Iterating

Once you have an initial version of the tool in place, **test the heck out of it**. Try everything you'd want as a regular user, and tune all aspects of the tool as needed: tool name, tool description, prompt of the context messages (`context_prompt_template`), and context from the frontend.

When developing, get full visibility into what the tool is doing using local PostHog LLM analytics: [http://localhost:8010/llm-analytics/traces](http://localhost:8010/llm-analytics/traces). Each _trace_ represents one human message submitted to Max, and shows the whole sequence of steps taken to answer that message.

If you've got any requests for Max, including around tools, let us know at #team-posthog-ai in Slack!

### Access control

MaxTools use **resource-level access control** to restrict tool execution based on user permissions (e.g., prevent creating feature flags if the user lacks editor access).
The access check runs automatically before `_arun_impl()` is called. If the user lacks permission, a `MaxToolAccessDeniedError` is raised with a clear message to the agent.

The main access check logic lives in `posthog/rbac/user_access_control.py`.

**To implement access control:**

1. Override `get_required_resource_access()` in your tool:

```python
def get_required_resource_access(self):
    return [("feature_flag", "editor")]  # Single resource
    # Or multiple: return [("dashboard", "editor"), ("insight", "viewer")]
```

Supported resources: see `APIScopeObject` in `posthog/scopes.py` (e.g., `feature_flag`, `dashboard`, `insight`, `experiment`, `survey`)
Access levels: `none`, `viewer`, `editor`, `manager`

2. Update `TOOLS_WITHOUT_ACCESS_CONTROL` in `ee/hogai/test/test_tool.py` to remove your tool from the exempt list.

**What's NOT implemented yet:** Object-level access control (e.g., filtering insights the user can access, or restricting edits to a dashboard). If you need this, check access in your `_arun_impl()` or in the ArtifactManager.

**Opting out:** If your tool doesn't need access control (read-only, no protected resources), add it to `TOOLS_WITHOUT_ACCESS_CONTROL` in `ee/hogai/test/test_tool.py`.

### Best practices for LLM-based tools

- Provide comprehensive context about current state from the frontend
- Test with diverse inputs and edge cases
- Keep prompts clear and structured with explicit rules
- Allow users to both get things done from scratch, and refine what's already there

For a _lot_ of great detail on prompting, check out the [GPT-4.1 prompting guide](https://cookbook.openai.com/examples/gpt4-1_prompting_guide). While somewhat GPT-4.1 specific, those principles largely apply to LLMs overall.

## Support new query types

PostHog AI can now read from frontend context multiple query types like trends, funnels, retention, and HogQL queries. To add support for new query types, you need to extend both the QueryExecutor and the Root node.

NOTE: this won't extend query types generation. For that, talk to the PostHog AI team.

### Adding a new query type

1. **Update the query executor and formatters** (`@ee/hogai/context/insight/`):
   - Add a new formatter class in `context/insight/format/` that implements query result formatting for AI consumption. Make sure it's imported and exported from `context/insight/format/__init__.py`. See below (Step 3) for more information.
   - Add formatting logic to `_compress_results()` method in `context/insight/query_executor.py`:

     ```python
     elif isinstance(query, YourNewAssistantQuery | YourNewQuery):
         return YourNewResultsFormatter(query, response["results"]).format()
     ```

   - Add example prompts for your query type in `context/insight/prompts.py`, this explains to the LLM the query results formatting
   - Update `get_example_prompt()` function in `context/insight/query_executor.py` to handle your new query type:

     ```python
     if isinstance(viz_message.answer, YourNewAssistantQuery):
         return YOUR_NEW_EXAMPLE_PROMPT
     ```

2. **Create the formatter class**:

   Create a new formatter in `format/your_formatter.py` following the pattern of existing formatters:

   ```python
   class YourNewResultsFormatter:
       def __init__(self, query: YourNewQuery, results: dict, team: Optional[Team] = None, utc_now_datetime: Optional[datetime] = None):
           self._query = query
           self._results = results
           self._team = team
           self._utc_now_datetime = utc_now_datetime

       def format(self) -> str:
           # Format your query results for AI consumption
           # Return a string representation optimized for LLM understanding
           pass
   ```

3. **Add tests**:
   - Add test cases in `test/test_query_executor.py` for your new query type
   - Add test cases in `test/format/test_format.py` for your new formatter
   - Ensure tests cover both successful execution and error handling

### Taxonomy Agent

Build small, focused agentic RAG-style agents that browse the team's taxonomy (events, entity properties, event properties) and produce a structured answer.

#### Quickstart

1. Define your structured output (what the agent must return):

```python
from pydantic import BaseModel

class MaxToolTaxonomyOutput(BaseModel):
    # The schema that the agent should return as a response
    # See an example: from posthog.schema import MaxRecordingUniversalFilters
```

2. Create a toolkit and add a typed `final_answer` tool (optional: change output formatting to YAML) and any custom tool you might have, in this example `hello_world`:

```python
from pydantic import BaseModel, Field
from ee.hogai.chat_agent.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.chat_agent.taxonomy.tools import base_final_answer
from posthog.models import Team


class final_answer(base_final_answer[MaxToolTaxonomyOutput]):
    # Usually the final answer tool will be different for each max_tool based on the expected output.
    __doc__ = base_final_answer.__doc__ # Inherit from the base final answer or create your own.

class hello_world(BaseModel):
    """Tool for saying hello to the user, should be used in the very beginning of the conversation. Use it before you use any other tool."""
    name: str = Field(description="The name of the person to say hello to.")

def hello_world_tool(name: str) -> str:
    return f"Hello, {name}!"

class YourToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team):
        super().__init__(team)

    # You must override this method if you are adding a custom tool that is only applicable to your usecase
    def handle_tools(self, tool_name: str, tool_input: TaxonomyTool) -> tuple[str, str]:
        """Override the handle_tools method to add custom tools."""
        if tool_name == "hello_world":
            result = hello_world_tool(tool_input.arguments.name)
            return tool_name, result
        return super().handle_tools(tool_name, tool_input)

    def _get_custom_tools(self) -> list:
        return [final_answer, hello_world]

    # Optional: prefer YAML over XML for property lists, but not a must to override
    # If not overriden XML will be used
    def _format_properties(self, props: list[tuple[str, str | None, str | None]]) -> str:
        return self._format_properties_yaml(props)
```

3. Define the loop and tools nodes, then bind them in a graph:

```python
from langchain_core.prompts import ChatPromptTemplate
from posthog.models import Team, User
from ee.hogai.chat_agent.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.chat_agent.taxonomy.agent import TaxonomyAgent
from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState

class LoopNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[MaxToolTaxonomyOutput]]):
    def __init__(self, team: Team, user: User, toolkit_class: type[YourToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """
        To allow for maximum flexibility you override the system prompt to tailor the taxonomy search agent to your needs.
        The taxonomy agent comes with some prepackaged default prompts. Check them here ee/hogai/graph/taxonomy/prompts.py
        """
        system = [
            "Here you add your custom prompt, you can define things like taxonomy operators, filter logic, or any other instruction you need for your usecase.",
            *super()._get_default_system_prompts(), # You can reuse the default prompts we provide if they match your criteria
        ]
        return ChatPromptTemplate([("system", m) for m in system], template_format="mustache")


class ToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[MaxToolTaxonomyOutput]]):
    """
    This is the tool node where the tool call flow and the tool execution is handled.
    You can override the methods to your needs, although in most cases you shall not need to do so.
    """
    def __init__(self, team: Team, user: User, toolkit_class: type[YourToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)


class YourTaxonomyGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[MaxToolTaxonomyOutput]]):
    def __init__(self, team: Team, user: User, tool_call_id: str):
        super().__init__(
            team,
            user,
            tool_call_id,
            loop_node_class=LoopNode,
            tools_node_class=ToolsNode,
            toolkit_class=YourToolkit,
        )
```

4. Invoke it (typically from a `MaxTool`), mirroring `products/replay/backend/max_tools.py`:

```python
graph = YourTaxonomyGraph(team=self._team, user=self._user)

graph_context = {
    "change": "Show me recordings of users in Germany that used a mobile device while performing a payment",
    "output": None,
    "tool_progress_messages": [],
    **self.context,
}

result = await graph.compile_full_graph().ainvoke(graph_context)

# Currently we support Pydantic objects or str as an output type
if isinstance(result["output"], MaxToolTaxonomyOutput):
    content = "✅ Updated taxonomy selection"
    payload = result["output"]
else:
    content = "❌ Need more info to proceed"
    payload = MaxToolTaxonomyOutput.model_validate(result["output"])
```

See `products/replay/backend/max_tools.py` for a full real-world example wiring a taxonomy agent into a `MaxTool`.

### Key considerations

- **Query execution**: The `AssistantQueryExecutor` class handles the complete query lifecycle including async polling and error handling
- **Result formatting**: Each query type needs a specialized formatter that converts raw results into AI-readable format
- **Error handling**: The system provides fallback to raw JSON if custom formatting fails
- **Context awareness**: The root node provides UI context (dashboards, insights, events, actions) to help the AI understand the current state
- **Memory integration**: The system can access core memory and onboarding state to provide contextual responses

The query executor is designed to be extensible while maintaining robustness through comprehensive error handling and fallback mechanisms.
