from typing import Literal

from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import TodoItem

TODO_WRITE_PROMPT = """
Use this tool to build and maintain a structured to-do list for the current session. It helps you monitor progress, organize complex work, and show thoroughness. It also makes both task progress and the overall status of the user’s requests clear to the user.

# When to use this tool
Use it proactively in these situations:

1. Complex, multi-step work – when a task needs 3+ distinct steps or actions
2. Non-trivial tasks – work that requires careful planning or multiple operations
3. User explicitly asks for a to-do list – when they request it directly
4. User supplies multiple tasks – e.g., a numbered or comma-separated list
5. After new instructions arrive – immediately capture the requirements as to-dos
6. When you begin a task – set it to `in_progress` BEFORE starting; ideally only one `in_progress` item at a time
7. After finishing a task – mark it `completed` and add any follow-ups discovered during execution

# When NOT to use this tool
Skip it when:
1. There’s only a single, straightforward task
2. The task is trivial and tracking adds no organizational value
3. It can be finished in fewer than 3 trivial steps
4. The exchange is purely conversational or informational

NOTE: If there’s just one trivial task, don’t use the tool–simply do the task directly.

# Examples of when to use the todo list

<example>
User: how many users have chatted with the AI assistant from the US?
Assistant: I'll help you find the number of users who have chatted with the AI assistant from the US. Let me create a todo list to track this implementation.
*Creates todo list with the following items:*
1. Find the relevant events to "chatted with the AI assistant"
2. Find the relevant properties of the events and persons to narrow down data to users from specific country
3. Retrieve the sample property values for found properties
4. Create the structured plan of the insight by using the data retrieved in the previous steps
5. Generate the insight
6. Analyze retrieved data
*Begins working on the first task*

<reasoning>
The assistant used the todo list because:
1. Creating an insight requires understanding the taxonomy: events, properties, and property values are relevant to the user's query.
2. The user query requests additional segmentation.
3. Property values might require retrieving sample property values to understand the data better.
4. Property values sample might not contain the value the user is looking for, so searching might be necessary.
5. Taxonomy might have multiple combinations of data that will equally answer the question.
</reasoning>
</example>

<example>
User: Has eleventy churned?
Assistant: Let me first search for a company with name "eleventy".
*Uses the search tool to find a property value with the "eleventy" value in the project*
Assistant: I've found a property value with the "Eleventy.ai" value. I'm going to search for existing insights tracking the customer churn rate.
*Uses the search tools to find insights tracking the customer churn rate in the project*
Assistant: I've found 0 matching insights. Let me create a new insight checking if the company "Eleventy.ai" has churned. I'm going to create a todo list to track these changes.
*Creates a todo list with specific steps to create a new insight*

<reasoning>
The assistant used the todo list because:
1. First, the assistant searched to understand the scope of the task
2. After the assistant verified that there isn't an insight tracking the customer churn rate, it determined this was a complex task with multiple steps
3. The todo list helps ensure every instance is tracked and updated systematically
</reasoning>
</example>

<example>
User: Check why onboarding completion rate has dropped and if it is connected with a low sign-up count
Assistant: I'll help you analyze the reasons why the metrics have changed. First, let's add all the features to the todo list.
*Creates a todo list breaking down each analysis into specific tasks based on the project data*
Assistant: Let's start with analyzing the sign-up count. This will involve retrieving the events and might involve retrieving additional data.

<reasoning>
The assistant used the todo list because:
1. The user requested multiple complex analysis for different metrics that must be separate insights
2. The todo list helps organize these large requests into manageable tasks
3. This approach allows for tracking progress across the entire request
</reasoning>
</example>

# Examples of when NOT to use the todo list

<example>
User: What does this query do?
Assistant: Let me analyze the query you provided.
*Reads the attached context in the conversation history*
Assistant: The query is retrieving the sign-up count for the last 30 days.

<reasoning>
The assistant did not use the todo list because this is a single, trivial task that can be completed in one step. There's no need to track multiple tasks or steps for such a straightforward request.
</reasoning>
</example>

<example>
User: How can I capture exception in my Next.js application?
Assistant: Let me search for the relevant documentation.
*Uses the search tool to find the relevant documentation*
Assistant: I've found the relevant documentation.
*Summarizes and returns the answer to the user's question*

<reasoning>
The assistant did not use the todo list because this is an informational request. The user is simply asking for help, not for the assistant to perform multiple steps or tasks.
</reasoning>
</example>

# Task states and management

1. **Task States**: Use these states to track progress:
  - pending: Task not yet started
  - in_progress: Currently working on (limit to ONE task at a time)
  - completed: Finished successfully

2. **Managing Tasks**:
  - Update statuses in real time as you work
  - Mark tasks complete IMMEDIATELY when done–don’t batch them
  - Keep only ONE task `in_progress` at any moment
  - Finish the current task before starting another
  - Remove tasks that are no longer relevant

3. **Completion Rules**:
  - Mark a task `completed` only when it’s FULLY done
  - If you hit errors, blockers, or can’t finish, leave it `in_progress`
  - When blocked, add a new task describing what must be resolved
  - Never mark `completed` if:
    - Implementation is partial
    - Required data couldn’t be found

4. **Task Breakdown**:
  - Create specific, actionable items
  - Break complex tasks into smaller, manageable steps
  - Use clear, descriptive task names

When unsure, use this tool. Proactive task management shows attentiveness and helps ensure all requirements are met.
""".strip()


class TodoWriteToolArgs(BaseModel):
    todos: list[TodoItem] = Field(..., description="The updated todo list")


class TodoWriteTool(MaxTool):
    name: Literal["todo_write"] = "todo_write"
    description: str = TODO_WRITE_PROMPT
    args_schema: type[BaseModel] = TodoWriteToolArgs

    async def _arun_impl(self, todos: list[TodoItem]) -> tuple[str, None]:
        return (
            "The to-dos were updated successfully. Please keep using the to-do list to track your progress, and continue with any active tasks as appropriate.",
            None,
        )
