from typing import Any, Literal

from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

from posthog.schema import FormResumePayload, MultiQuestionForm, MultiQuestionFormQuestion

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

CREATE_FORM_PROMPT = """
Use this tool to gather structured information from users through an interactive multi-question form.

## When to Use This Tool

- Clarify ambiguous requirements before proceeding
- Gather user preferences when multiple valid approaches exist
- Collect context needed to provide better recommendations
- Get decisions on choices that affect the outcome

## Question Structure

Each question requires:
- `id`: Unique identifier (e.g., "goal", "timeframe", "metric_type")
- `title`: Short tab label, 1-2 words (e.g., "Goal", "Timeframe", "Metric")
- `question`: Clear, specific question ending with "?" (e.g., "What is your primary goal for this analysis?")
- `options`: 2-4 distinct choices, each with:
  - `value`: Concise answer (1-5 words) shown as button text
  - `description` (optional): Brief explanation of what this choice means
- `allow_custom_answer`: Set to false only when custom answers don't make sense

## When to Use Descriptions

Include descriptions when:
- Options need clarification (e.g., "Trends" → "Track metrics over time")
- Users might not understand implications of a choice
- Options are domain-specific or technical

Omit descriptions when:
- Options are self-explanatory (e.g., "7 days", "30 days", "90 days")
- Options are simple yes/no or numeric choices
- The value text is already clear enough

## Guidelines

- Keep questions focused and independent when possible
- If you recommend a specific option, list it first with "(Recommended)" in the value
- Order options from most common/recommended to least
- Use sentence casing for all text
- Maximum 4 questions per form - split into multiple forms if needed

## Example

```json
{
  "questions": [
    {
      "id": "analysis_goal",
      "title": "Goal",
      "question": "What is your primary goal for this analysis?",
      "options": [
        {"value": "Understand user behavior", "description": "See how users interact with your product"},
        {"value": "Measure conversion", "description": "Track how users move through a funnel"},
        {"value": "Compare segments", "description": "Analyze differences between user groups"}
      ]
    }
  ]
}
```
"""


class CreateFormToolArgs(BaseModel):
    questions: list[MultiQuestionFormQuestion] = Field(..., description="The questions to ask the user")


class CreateFormTool(MaxTool):
    name: Literal["create_form"] = "create_form"
    args_schema: type[BaseModel] = CreateFormToolArgs
    description: str = CREATE_FORM_PROMPT

    async def _arun_impl(self, questions: list[MultiQuestionFormQuestion]) -> tuple[str, Any]:
        if not questions:
            raise MaxToolRetryableError("At least one question is required.")
        if len(questions) > 4:
            raise MaxToolRetryableError("Do not ask more than 4 questions at a time.")
        response = interrupt(value=MultiQuestionForm(questions=questions))
        try:
            form_payload = FormResumePayload.model_validate(response)
        except ValidationError as e:
            raise MaxToolRetryableError(f"Invalid response from the user: {e}")

        # Handle the response from the user
        formatted_response = "\n".join([f"{q.question}: {form_payload.form_answers.get(q.id, '')}" for q in questions])
        return formatted_response, {
            "answers": form_payload.form_answers,
        }
