# PostHog AI

This directory contains the PostHog AI platform and its core features - known as Max AI.

[Getting started with Max.](https://posthog.slack.com/docs/TSS5W8YQZ/F08UU1LJFUP)

## For product teams: MaxTool

Add new capabilities to our AI assistant Max using the MaxTool API. You can allow Max to do anything in your product: both perform backend actions and control the UI. A tool can itself involve an LLM call based on a prompt tailored to the tool's task, using arguments provided to the tool by the Max root + context passed from the frontend.

To implement a MaxTool you first define it in the backend, then you mount it in the frontend. The backend definition contains the tool's metadata for Max (what is it, how to use it, when to use it, what arguments it takes) and its actual implementation. The frontend React mount point makes the tool available to Max - i.e. the tool is only available when the UI being automated is present.

You'll need to set [env vars](https://posthog.slack.com/docs/TSS5W8YQZ/F08UU1LJFUP) in order to hack on this – just ask in #team-max-ai to get those API keys.

> [!NOTE]
> Max AI is currently behind the `artificial-hog` flag - make sure to enable it.

### Defining

1. Create the `max_tools.py` file for your product, if it doesn't exist already: `products/<your product>/backend/max_tools.py`. `max_tools.py` files following this convention are automatically discovered and loaded by the system.

2. In your `max_tools.py`, define a new tool class inheriting from `MaxTool`:

    ```python
    from ee.hogai.tool import MaxTool
    from pydantic import BaseModel, Field
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate

    # Define your tool's arguments schema
    class YourToolArgs(BaseModel):
        parameter_name: str = Field(description="Description of the parameter")

    class YourTool(MaxTool):
        name: str = "your_tool_name"  # Must match a value in AssistantContextualTool enum
        description: str = "What this tool does"
        thinking_message: str = "What to show while tool is working"
        root_system_prompt_template: str = "Context about the tool state: {context_var}" 
        args_schema: type[BaseModel] = YourToolArgs

        async def _arun_impl(self, parameter_name: str) -> tuple[str, Any]:
            # Implement tool logic here
            # Access context with self.context (must have context_var from template)
            # If you use Django's ORM, ensure you utilize its asynchronous capabilities.
            
            # Optional: Use LLM to process inputs or generate structured outputs
            model = (
                ChatOpenAI(model="gpt-4o", temperature=0.2)
                .with_structured_output(OutputType)
                .with_retry()
            )

            response = model.ainvoke({"question": "What is PostHog?"})
            
            # Process and return results as (message, structured_data)
            return "Tool execution completed", result_data
    ```

3. Add your tool name to the `AssistantContextualTool` union in `frontend/src/queries/schema/schema-assistant-messages.ts`, then run `pnpm schema:build`.

For an example, see `products/replay/backend/max_tools.py`, which defines the `search_session_recordings` tool, and `products/data_warehouse/backend/max_tools.py`, which defines the `generate_hogql_query` tool.

### Mounting

1. Use the `MaxTool` component to wrap UI elements that can benefit from AI assistance:

```tsx
import { MaxTool } from 'scenes/max/MaxTool'

function YourComponent() {
    return (
        <MaxTool
            name="your_tool_name"  // Must match backend tool name - enforced by the AssistantContextualTool enum
            displayName="Human-friendly name"
            context={{
                // Context data passed to backend - can be empty if there truly is no context
                context_var: relevantData,
            }}
            callback={(toolOutput) => {
                // Handle structured output from tool
                updateUIWithToolResults(toolOutput);
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

For an example, see `frontend/src/scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed.tsx`, which mounts the `search_session_recordings` tool.

## Iterating

Once you have an initial version of the tool in place, **test the heck out of it**. Try everything you'd want as a regular user, and tune all aspects of the tool as needed: prompt, description, `root_system_prompt_template`, context from the frontend.

When developing, get full visibility into what the tool is doing using local PostHog LLM observability: [http://localhost:8010/llm-observability/traces](http://localhost:8010/llm-observability/traces). Each _trace_ represents one human message submitted to Max, and shows the whole sequence of steps taken to answer that message.

If you've got any requests for Max, including around tools, let us know at #team-max-ai in Slack!

## Best practices for LLM-based tools

- Provide comprehensive context about current state from the frontend
- Test with diverse inputs and edge cases
- Keep prompts clear and structured with explicit rules
- Allow users to both get things done from scratch, and refine what's already there

For a _lot_ of great detail on prompting, check out the [GPT-4.1 prompting guide](https://cookbook.openai.com/examples/gpt4-1_prompting_guide). While somewhat GPT-4.1 specific, those principles largely apply to LLMs overall.

## Support new query types

Max can now read from frontend context multiple query types like trends, funnels, retention, and HogQL queries. To add support for new query types, you need to extend both the QueryExecutor and the Root node.

NOTE: this won't extend query types generation. For that, talk to the Max AI team.

### Adding a new query type

1. **Update the query executor** (`@ee/hogai/graph/query_executor/`):

   - Add your new query type to the `SupportedQueryTypes` union in `query_executor.py:33`:
     ```python
     SupportedQueryTypes = (
         AssistantTrendsQuery
         | TrendsQuery
         | AssistantFunnelsQuery
         | FunnelsQuery
         | AssistantRetentionQuery
         | RetentionQuery
         | AssistantHogQLQuery
         | HogQLQuery
         | YourNewQuery           # Add your query type
     )
     ```

   - Add a new formatter class in `query_executor/format.py` that implements query result formatting for AI consumption (see below, point 3)
   - Add formatting logic to `_compress_results()` method in `query_executor/query_executor.py`:
     ```python
     elif isinstance(query, YourNewAssistantQuery | YourNewQuery):
         return YourNewResultsFormatter(query, response["results"]).format()
     ```
   - Add example prompts for your query type in `query_executor/prompts.py`, this explains to the LLM the query results formatting
   - Update `_get_example_prompt()` method in `query_executor/nodes.py` to handle your new query type:
     ```python
     if isinstance(viz_message.answer, YourNewAssistantQuery):
         return YOUR_NEW_EXAMPLE_PROMPT
     ```

2. **Update the root node** (`@ee/hogai/graph/root/`):

   - Add your new query type to the `MAX_SUPPORTED_QUERY_KIND_TO_MODEL` mapping in `nodes.py:57`:
     ```python
     MAX_SUPPORTED_QUERY_KIND_TO_MODEL: dict[str, type[SupportedQueryTypes]] = {
         "TrendsQuery": TrendsQuery,
         "FunnelsQuery": FunnelsQuery,
         "RetentionQuery": RetentionQuery,
         "HogQLQuery": HogQLQuery,
         "YourNewQuery": YourNewQuery,  # Add your query mapping
     }
     ```

3. **Create the formatter class**:
   
   Create a new formatter in `format.py` following the pattern of existing formatters:
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

4. **Add tests**:
   - Add test cases in `test/test_query_executor.py` for your new query type
   - Add test cases in `test/test_format.py` for your new formatter
   - Ensure tests cover both successful execution and error handling

### Key considerations

- **Query execution**: The `AssistantQueryExecutor` class handles the complete query lifecycle including async polling and error handling
- **Result formatting**: Each query type needs a specialized formatter that converts raw results into AI-readable format
- **Error handling**: The system provides fallback to raw JSON if custom formatting fails
- **Context awareness**: The root node provides UI context (dashboards, insights, events, actions) to help the AI understand the current state
- **Memory integration**: The system can access core memory and onboarding state to provide contextual responses

The query executor is designed to be extensible while maintaining robustness through comprehensive error handling and fallback mechanisms.
