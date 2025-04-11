# PostHog AI

This directory contains the PostHog AI platform and its core features - known as Max AI.

## For product teams: MaxTool

The MaxTool API allows any PostHog product team to easily add new capabilities to our AI assistant Max.

A MaxTool always has two sides:

1. The backend definition, which contains the tool's metadata for Max (what is it, how to use it, when to use it, what arguments it takes) and its actual implementation (which can involve an LLM call too, but doesn't have to).
2. The frontend integration, which mounts the tool when the UI being automated is present. A MaxTool is only available to Max when mounted.

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

        def _run_impl(self, parameter_name: str) -> tuple[str, Any]:
            # Implement tool logic here
            # Access context with self.context (must have context_var from template)
            
            # Optional: Use LLM to process inputs or generate structured outputs
            model = (
                ChatOpenAI(model="gpt-4o", temperature=0.2)
                .with_structured_output(OutputType)
                .with_retry()
            )
            
            # Process and return results as (message, structured_data)
            return "Tool execution completed", result_data
    ```

3. Add your tool name to the `AssistantContextualTool` union in `frontend/src/queries/schema/schema-assistant-messages.ts`, then run `pnpm schema:build`.

For an example, see `products/replay/backend/max_tools.py`, which defines the `search_session_recordings` tool.

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

For an example, see `frontend/src/scenes/session-recordings/filters/RecordingsUniversalFilters.tsx`, which mounts the `search_session_recordings` tool.

## Best practices for LLM-based tools

- Provide comprehensive context about current state from the frontend
- Test with diverse inputs and edge cases
- Keep prompts clear and structured with explicit rules
- Allow users to both get things done from scratch, and refine what's already there
