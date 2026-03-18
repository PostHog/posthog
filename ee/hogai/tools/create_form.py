from typing import Any, Literal

from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError

from posthog.schema import (
    FormDismissPayload,
    FormResumePayload,
    MultiQuestionForm,
    MultiQuestionFormField,
    MultiQuestionFormQuestion,
)

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

CREATE_FORM_PROMPT = """
Use this tool to gather structured information from users through an interactive multi-question form.

## When to Use This Tool

- Clarify ambiguous requirements before proceeding
- Gather user preferences when multiple valid approaches exist
- Collect context needed to provide better recommendations
- Get decisions on choices that affect the outcome

## Philosophy

Always use the full capacity of the form (up to 4 questions). Each form is a single chance to gather context — maximize the information captured. Focus on parameters that materially affect the outcome: configuration values, thresholds, ratios, targeting criteria, metric choices. Skip superficial questions like names or descriptions that you can generate yourself. Every question should directly change what you build or how you build it. Use optional fields to capture nice-to-have context without blocking submission. Default to being thorough — the user should not have to ask for detail.

Users can skip individual questions or dismiss the form entirely, so only ask questions whose answers materially change the outcome.

Never ask for confirmation of something you can infer from the conversation. If the user said "create an experiment for the checkout flow", you already know the target area — don't ask again. Only ask about parameters that are genuinely ambiguous or have multiple valid choices.

Every select option must be a concrete, actionable value — never a vague category that requires follow-up. If an option would just lead to another question (e.g., "Specific user segment"), it's useless. Either provide the actual specific choices (e.g., list real cohorts or properties) or use a `multi_field` text input instead.

For example, when creating an experiment, ask about the test/control ratio, the target metric, the minimum sample size, and the significance level — not the experiment name.

## Question Types

There are three question types:

### `select` (default) — single-select radio buttons
- Requires `options`: 2-4 choices with `value` and optional `description`
- `allow_custom_answer`: Set to false only when custom answers don't make sense
- Include descriptions when options need clarification or are domain-specific
- Omit descriptions when options are self-explanatory (e.g., "7 days", "30 days")

### `multi_select` — checkboxes for multiple selections
- Requires `options`: 2-4 choices with `value` and optional `description`
- Returns an array of selected values

### `multi_field` — multiple compact fields grouped on one page
- Set `type` to `multi_field` and provide a `fields` array
- Renders all fields together with a shared submit button
- Each field has `id`, `type` (required), and `label`
- Allowed field types: `text`, `number`, `slider`, `toggle`, `dropdown`
- **Maximum 1 multi_field question per form**
- **All non-selection inputs MUST go here** — text, number, slider, toggle, and dropdown cannot be standalone questions

Field type details:
- `text`: free text input. Optional `placeholder`
- `number`: numeric input. Optional `min`, `max`, `step`, `placeholder`
- `slider`: numeric slider. Requires `min` and `max`. Optional `step` (default: 1)
- `toggle`: on/off switch. Returns "true" or "false"
- `dropdown`: single-select dropdown. Requires `options` with `value` and optional `description`

All field types support `optional: true` to let the user skip the field.

## When to Use Each Type

- Use `select` when there are 2-4 predefined choices and the user picks one
- Use `multi_select` when the user can pick multiple from 2-4 predefined choices
- Use `multi_field` when you need **any** free-form input: names, numbers, thresholds, on/off settings, or any value that can't be reduced to a small set of choices. Even a single text or number input must be wrapped in a `multi_field` question. This is the best way to collect configuration parameters — always include one when creating something configurable (experiments, feature flags, alerts, etc.).

### Picking the right field type inside `multi_field`

- Any numeric parameter (sample sizes, percentages, ratios, thresholds, days, counts) → use `number` or `slider`, never `text`
- Bounded numeric ranges (confidence level 80-99%, rollout 0-100%) → use `slider` with appropriate `min`/`max`/`step`
- Unbounded or large-range numbers (sample size, revenue threshold) → use `number` with `placeholder`
- Boolean settings (enable/disable, yes/no) → use `toggle`, never a select with two options
- Free-form strings (event names, URLs, descriptions) → use `text`
- Picking from a known list inside a composite question → use `dropdown`

## Rules

- `select` and `multi_select` require `options` (2-4 choices)
- `multi_field` requires `fields` — group all non-selection inputs into one `multi_field` question
- Do not force a `select` when the answer is open-ended — use a `multi_field` with a `text` field instead
- Do not force a `select` with numeric ranges — use a `multi_field` with a `number` or `slider` field instead
- If you recommend a specific option in a select, list it first with "(Recommended)" in the value
- Order options from most common/recommended to least
- Fields are required by default. Set `optional: true` on fields the user can skip
- Do not write "(optional)" in the label — the UI adds it automatically for optional fields
- Use sentence casing for all text
- Maximum 4 questions per form, maximum 1 `multi_field` question per form

## Examples

### Experiment configuration
Mixed form with selection and free-form inputs for setting up an A/B test:
```json
{
  "questions": [
    {
      "id": "metric",
      "title": "Metric",
      "question": "What is the primary metric for this experiment?",
      "options": [
        {"value": "Conversion rate", "description": "Percentage of users who complete the target action"},
        {"value": "Revenue per user", "description": "Average revenue generated per user in the test"},
        {"value": "Retention (day 7)", "description": "Percentage of users who return after 7 days"}
      ]
    },
    {
      "id": "experiment_config",
      "title": "Config",
      "type": "multi_field",
      "question": "Configure your experiment",
      "fields": [
        {"id": "min_sample", "type": "number", "label": "Minimum sample size", "min": 100, "max": 100000, "placeholder": "e.g. 1000"},
        {"id": "traffic_split", "type": "slider", "label": "Traffic to test group (%)", "min": 10, "max": 50, "step": 5},
        {"id": "confidence", "type": "slider", "label": "Confidence level (%)", "min": 80, "max": 99, "step": 1}
      ]
    }
  ]
}
```

### Research — scoping a user behavior analysis
Interviewing the user to understand what they want to learn before building an insight:
```json
{
  "questions": [
    {
      "id": "analysis_goal",
      "title": "Goal",
      "question": "What do you want to understand about your users?",
      "options": [
        {"value": "Where users drop off in a flow", "description": "Identify the biggest friction points in a specific journey"},
        {"value": "What power users do differently", "description": "Compare behavior of high-value users vs the rest"},
        {"value": "Impact of a recent change", "description": "Measure how a release or feature change affected metrics"}
      ]
    },
    {
      "id": "scope",
      "title": "Scope",
      "type": "multi_field",
      "question": "Help me narrow the scope",
      "fields": [
        {"id": "flow_or_feature", "type": "text", "label": "Which flow or feature area?", "placeholder": "e.g. onboarding, checkout, invite flow"},
        {"id": "timeframe", "type": "dropdown", "label": "Time range", "options": [{"value": "Last 7 days"}, {"value": "Last 30 days"}, {"value": "Last 90 days"}]},
        {"id": "segment", "type": "text", "label": "Any specific user segment?", "placeholder": "e.g. paid users, mobile users", "optional": true}
      ]
    }
  ]
}
```

### Planning — clarifying requirements for a dashboard
Gathering context before building a monitoring dashboard:
```json
{
  "questions": [
    {
      "id": "audience",
      "title": "Audience",
      "question": "Who will use this dashboard?",
      "options": [
        {"value": "Engineering team", "description": "Focus on performance, errors, and system health"},
        {"value": "Product team", "description": "Focus on adoption, engagement, and feature usage"},
        {"value": "Leadership", "description": "Focus on high-level KPIs and growth trends"}
      ]
    },
    {
      "id": "focus_areas",
      "title": "Focus",
      "type": "multi_select",
      "question": "Which areas should the dashboard cover?",
      "options": [
        {"value": "Acquisition", "description": "Signups, activation, and first-time usage"},
        {"value": "Engagement", "description": "DAU/WAU/MAU, session frequency, feature adoption"},
        {"value": "Retention", "description": "Cohort retention, churn indicators"},
        {"value": "Revenue", "description": "Conversion to paid, expansion, MRR"}
      ]
    },
    {
      "id": "details",
      "title": "Details",
      "type": "multi_field",
      "question": "Additional details",
      "fields": [
        {"id": "key_event", "type": "text", "label": "Most important event to track", "placeholder": "e.g. purchase_completed, report_generated"},
        {"id": "compare_periods", "type": "toggle", "label": "Include period-over-period comparisons"}
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

        # Coalesce multiple multi_field questions into one to avoid showing a broken form.
        # The frontend renders the form from the streamed tool call args before validation runs,
        # so raising a retryable error here would flash a form then discard it.
        multi_field_questions = [q for q in questions if (q.type or "select") == "multi_field"]
        if len(multi_field_questions) > 1:
            merged_fields = []
            for q in multi_field_questions:
                if q.fields:
                    merged_fields.extend(q.fields)
            multi_field_questions[0].fields = merged_fields
            questions = [q for q in questions if (q.type or "select") != "multi_field"] + [multi_field_questions[0]]

        for q in questions:
            question_type = q.type or "select"
            if question_type == "multi_field":
                if not q.fields:
                    q.fields = []
                for field in q.fields:
                    self._validate_field(field, q.id)
            else:
                if not q.options:
                    raise MaxToolRetryableError(f"Question '{q.id}' with type '{question_type}' requires options.")

        response = interrupt(value=MultiQuestionForm(questions=questions))
        try:
            form_payload = FormResumePayload.model_validate(response)
        except ValidationError:
            try:
                dismiss_payload = FormDismissPayload.model_validate(response)
            except ValidationError as e:
                raise MaxToolRetryableError(f"Invalid response from the user: {e}")

            return (
                "The user dismissed the form and chose not to answer these questions. "
                "Continue without these answers if possible. If the missing information is required, "
                "briefly explain what is blocked and offer the user a lower-friction alternative.",
                {
                    "status": dismiss_payload.action,
                },
            )

        def format_answer(answer: str | list[str] | None) -> str:
            if answer is None:
                return "(skipped)"
            if isinstance(answer, list):
                return ", ".join(answer)
            return answer

        lines: list[str] = []
        for q in questions:
            if q.fields:
                lines.append(f"{q.question}:")
                for field in q.fields:
                    lines.append(f"  {field.label}: {format_answer(form_payload.form_answers.get(field.id))}")
            else:
                lines.append(f"{q.question}: {format_answer(form_payload.form_answers.get(q.id))}")

        return "\n".join(lines), {
            "status": "form",
            "answers": form_payload.form_answers,
        }

    @staticmethod
    def _validate_field(field: MultiQuestionFormField, question_id: str) -> None:
        if field.type == "dropdown" and not field.options:
            raise MaxToolRetryableError(
                f"Field '{field.id}' in question '{question_id}' with type 'dropdown' requires options."
            )
        if field.type == "slider" and (field.min is None or field.max is None):
            raise MaxToolRetryableError(
                f"Field '{field.id}' in question '{question_id}' with type 'slider' requires min and max."
            )
