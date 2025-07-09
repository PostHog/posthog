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
