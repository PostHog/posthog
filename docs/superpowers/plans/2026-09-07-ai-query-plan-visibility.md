# AI Query Plan Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show AI prompt subscription owners whether the next delivery will reuse a frozen query plan, create one, or regenerate one after a planner compatibility change.

**Architecture:** Keep `ai_query_plan` private and derive a read-only lifecycle enum from it. A single backend validator/classifier owns both the delivery reuse decision and the API status, while a focused frontend component maps the generated enum to a compact accessible icon and explanatory tooltip.

**Tech Stack:** Django REST Framework, Pydantic, pytest, drf-spectacular/OpenAPI generation, React, TypeScript, LemonUI, Jest, Storybook.

**Spec:** `docs/superpowers/specs/2026-09-07-ai-query-plan-visibility-design.md`

## Global Constraints

- Planner upgrades remain automatic; do not add freeze, unfreeze, version pinning, or update controls.
- Return `null` for non-AI subscriptions and only `frozen`, `not_frozen`, or `planner_updated` for AI prompt subscriptions.
- `planner_updated` reflects `AI_QUERY_PLAN_VERSION`, not every internally managed LLM prompt revision.
- A frozen plan reuses query definitions while date ranges, results, and written report content still update.
- Use one plan-level icon: `IconPinFilled`, `IconPin`, or `IconRefresh`; do not use lock or snowflake imagery.
- The icon must be keyboard-focusable and have a complete accessible label without depending on hover.
- Treat corrupt stored JSON as recoverable and never expose the plan, HogQL, planner prompt, model, or version number through this status.
- Preserve the exact sentence-case user-facing copy from the approved spec and do not use em dashes.

---

### Task 1: Centralize stored-plan validation and classification

**Files:**

- Modify: `products/exports/backend/temporal/subscriptions/ai_subscription/spec_generator.py:1-110,623-660`
- Test: `products/exports/backend/temporal/subscriptions/ai_subscription/test/test_spec_generator.py:21-50,875-950`

**Interfaces:**

- Produces: `AIQueryPlanStatus(StrEnum)` with `FROZEN`, `NOT_FROZEN`, and `PLANNER_UPDATED` values.
- Produces: `validate_stored_query_plan(ai_query_plan: object) -> tuple[QueryPlan, list[str]]`.
- Produces: `get_ai_query_plan_status(ai_query_plan: object | None) -> AIQueryPlanStatus`.
- Changes: `build_frozen_prompt(...)` consumes `validate_stored_query_plan` and converts every invalid envelope into `StoredPlanInvalidError`.

- [ ] **Step 1: Add failing lifecycle tests**

Extend `TestBuildFrozenPrompt` with literal current-version and stale-version envelopes. Cover the observable classifications and the runtime recovery boundary:

```python
def test_classifies_stored_plan_lifecycle(self) -> None:
    for stored, expected in [
        (None, "not_frozen"),
        ([], "not_frozen"),
        ({"version": True, "plan": {}}, "not_frozen"),
        ({"version": float(AI_QUERY_PLAN_VERSION), "plan": {}}, "not_frozen"),
        ({"version": AI_QUERY_PLAN_VERSION - 1, "plan": {}}, "planner_updated"),
        ({"version": AI_QUERY_PLAN_VERSION, "plan": {}}, "not_frozen"),
        (self._stored_plan(), "frozen"),
    ]:
        assert get_ai_query_plan_status(stored).value == expected
```

Add `[]`, a boolean version, a floating-point version, a current-version plan with non-list `relevant_events`, and a non-string relevant event to `test_invalid_stored_plan_raises_recoverable_error`. These cases must raise `StoredPlanInvalidError`, not `AttributeError`, `TypeError`, or `AiReportStageError`.

- [ ] **Step 2: Run the lifecycle tests and verify RED**

Run:

```bash
flox activate -- hogli test products/exports/backend/temporal/subscriptions/ai_subscription/test/test_spec_generator.py::TestBuildFrozenPrompt
```

Expected: FAIL because `AIQueryPlanStatus` and `get_ai_query_plan_status` do not exist, and the non-object envelope currently calls `.get` directly.

- [ ] **Step 3: Implement one validator and classifier**

Add the enum and helpers next to `StoredPlanInvalidError`:

```python
class AIQueryPlanStatus(StrEnum):
    FROZEN = "frozen"
    NOT_FROZEN = "not_frozen"
    PLANNER_UPDATED = "planner_updated"


def _stored_query_plan_envelope(ai_query_plan: object) -> dict[str, object]:
    if not isinstance(ai_query_plan, dict):
        raise StoredPlanInvalidError("Stored query plan envelope is malformed.")
    return ai_query_plan


def _stored_query_plan_version(envelope: dict[str, object]) -> int:
    version = envelope.get("version")
    if type(version) is not int:
        raise StoredPlanInvalidError("Stored query plan version is malformed.")
    return version


def validate_stored_query_plan(ai_query_plan: object) -> tuple[QueryPlan, list[str]]:
    envelope = _stored_query_plan_envelope(ai_query_plan)
    version = _stored_query_plan_version(envelope)
    if version != AI_QUERY_PLAN_VERSION:
        raise StoredPlanInvalidError("Stored query plan version is stale.")
    try:
        plan = QueryPlan.model_validate(envelope.get("plan"))
    except ValidationError as exc:
        raise StoredPlanInvalidError("Stored query plan is malformed.") from exc
    raw_relevant_events = envelope.get("relevant_events")
    if raw_relevant_events is None:
        relevant_events: list[str] = []
    elif isinstance(raw_relevant_events, list) and all(isinstance(event, str) for event in raw_relevant_events):
        relevant_events = list(raw_relevant_events)
    else:
        raise StoredPlanInvalidError("Stored query plan relevant events are malformed.")
    return plan, relevant_events


def get_ai_query_plan_status(ai_query_plan: object | None) -> AIQueryPlanStatus:
    if ai_query_plan is None:
        return AIQueryPlanStatus.NOT_FROZEN
    try:
        envelope = _stored_query_plan_envelope(ai_query_plan)
        version = _stored_query_plan_version(envelope)
    except StoredPlanInvalidError:
        return AIQueryPlanStatus.NOT_FROZEN
    if version != AI_QUERY_PLAN_VERSION:
        return AIQueryPlanStatus.PLANNER_UPDATED
    try:
        validate_stored_query_plan(ai_query_plan)
    except StoredPlanInvalidError:
        return AIQueryPlanStatus.NOT_FROZEN
    return AIQueryPlanStatus.FROZEN
```

Import `StrEnum` from `enum`. Change `build_frozen_prompt`'s `ai_query_plan` annotation to `object`, then replace its inline checks with:

```python
plan, relevant_events = validate_stored_query_plan(ai_query_plan)
```

- [ ] **Step 4: Run the lifecycle tests and verify GREEN**

Run the same focused `TestBuildFrozenPrompt` command. Expected: all cases pass, including the original no-LLM reuse assertions.

- [ ] **Step 5: Commit the runtime lifecycle boundary**

```bash
git add products/exports/backend/temporal/subscriptions/ai_subscription/spec_generator.py products/exports/backend/temporal/subscriptions/ai_subscription/test/test_spec_generator.py
git commit -S -m "fix(subscriptions): centralize frozen plan validation"
```

---

### Task 2: Expose the read-only API status and regenerate contracts

**Files:**

- Modify: `ee/api/subscription.py:1-70,274-370`
- Test: `ee/api/test/test_subscription.py:1-50,119-170,2786-2970,3055-3070`
- Regenerate: `products/subscriptions/frontend/generated/api.schemas.ts`
- Regenerate: `services/mcp/src/api/generated.ts`

**Interfaces:**

- Consumes: `AIQueryPlanStatus` and `get_ai_query_plan_status(ai_query_plan)` from Task 1.
- Produces: `SubscriptionApi.ai_query_plan_status`, nullable for non-AI resources and generated as `AiQueryPlanStatusEnumApi | null`.

- [ ] **Step 1: Add failing serializer/API contract tests**

Import `AI_QUERY_PLAN_VERSION` in `ee/api/test/test_subscription.py`. Add `ai_query_plan_status: None` to the exact non-AI subscription response assertion. Assert a newly created AI subscription returns `not_frozen`.

Define this module-level literal for the retrieval cases:

```python
VALID_AI_QUERY_PLAN = {
    "overall_intent": "Count events",
    "steps": [
        {
            "description": "Count matching events",
            "query_type": "hogql",
            "hogql": "SELECT count() FROM events WHERE {{date_range}}",
        }
    ],
}
```

Add a parameterized retrieval test under `TestAISubscriptionAPI` using independently written JSON fixtures:

```python
@parameterized.expand(
    [
        ("valid", {"version": AI_QUERY_PLAN_VERSION, "plan": VALID_AI_QUERY_PLAN}, "frozen"),
        ("stale", {"version": AI_QUERY_PLAN_VERSION - 1, "plan": {}}, "planner_updated"),
        ("boolean_version", {"version": True, "plan": VALID_AI_QUERY_PLAN}, "not_frozen"),
        ("floating_version", {"version": float(AI_QUERY_PLAN_VERSION), "plan": VALID_AI_QUERY_PLAN}, "not_frozen"),
        ("malformed_current", {"version": AI_QUERY_PLAN_VERSION, "plan": {}}, "not_frozen"),
    ]
)
def test_retrieve_exposes_query_plan_status(
    self,
    mock_is_cloud: MagicMock,
    mock_flag: MagicMock,
    mock_sync: MagicMock,
    _name: str,
    stored: object,
    expected: str,
) -> None:
    self._mock_temporal(mock_sync)
    sub_id = self._create_subscription_for("ai_prompt")
    Subscription.objects.filter(id=sub_id).update(ai_query_plan=stored)
    response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/{sub_id}/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["ai_query_plan_status"] == expected
```

Extend `test_editing_prompt_invalidates_frozen_query_plan` so its PATCH response is `not_frozen` after a prompt edit and preserves the prior status after a title-only edit.

- [ ] **Step 2: Run the API tests and verify RED**

Run:

```bash
flox activate -- hogli test ee/api/test/test_subscription.py::TestAISubscriptionAPI::test_retrieve_exposes_query_plan_status
```

Expected: FAIL because the response has no `ai_query_plan_status` field.

- [ ] **Step 3: Add the serializer field**

Import `AIQueryPlanStatus` and alias `get_ai_query_plan_status` to `derive_ai_query_plan_status` in `ee/api/subscription.py`. Add a documented `SerializerMethodField`, include it in `Meta.fields`, and declare its generated enum:

```python
ai_query_plan_status = serializers.SerializerMethodField(
    help_text=(
        "Query plan reuse state for AI prompt subscriptions: frozen, not_frozen, or planner_updated. "
        "Null for other subscription types."
    )
)

@extend_schema_field(
    serializers.ChoiceField(
        choices=[(status.value, status.value.replace("_", " ").capitalize()) for status in AIQueryPlanStatus],
        allow_null=True,
    )
)
def get_ai_query_plan_status(self, subscription: Subscription) -> Optional[str]:
    if subscription.resource_type != Subscription.ResourceType.AI_PROMPT:
        return None
    return derive_ai_query_plan_status(subscription.ai_query_plan).value
```

The alias lets the serializer method keep DRF's required `get_<field>` name without shadowing the lifecycle helper.

- [ ] **Step 4: Run all focused API assertions and verify GREEN**

Run:

```bash
flox activate -- hogli test ee/api/test/test_subscription.py::TestAISubscriptionAPI::test_retrieve_exposes_query_plan_status
flox activate -- hogli test ee/api/test/test_subscription.py::TestAISubscriptionAPI::test_editing_prompt_invalidates_frozen_query_plan
flox activate -- hogli test ee/api/test/test_subscription.py::TestAISubscriptionAPI::test_creates_ai_subscription
flox activate -- hogli test ee/api/test/test_subscription.py::TestSubscriptionTemporal::test_can_create_new_subscription
```

Expected: all selected tests pass and non-AI serialization remains `null`.

- [ ] **Step 5: Regenerate OpenAPI-derived contracts**

Run:

```bash
flox activate -- hogli build:openapi
```

Inspect `git diff --name-only` and `git diff`. Confirm changes are limited to the two declared generated files, the frontend enum has exactly `Frozen`, `NotFrozen`, and `PlannerUpdated`, the subscription field is nullable/read-only, and no raw plan or version appears in the contract.

- [ ] **Step 6: Commit the API contract**

```bash
git add ee/api/subscription.py ee/api/test/test_subscription.py
git add products/subscriptions/frontend/generated/api.schemas.ts services/mcp/src/api/generated.ts
git commit -S -m "feat(subscriptions): expose query plan status"
```

---

### Task 3: Render the compact status and correct delivery wording

**Files:**

- Create: `products/subscriptions/frontend/scenes/components/SubscriptionQueryPlanStatus.tsx`
- Create: `products/subscriptions/frontend/scenes/components/SubscriptionQueryPlanStatus.test.tsx`
- Create: `products/subscriptions/frontend/scenes/components/SubscriptionSummary.test.tsx`
- Create: `products/subscriptions/frontend/scenes/components/SubscriptionSummary.stories.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionSummary.tsx:1-95`
- Rename: `products/subscriptions/frontend/scenes/components/SubscriptionAiReportDelivery.test.ts` to `SubscriptionAiReportDelivery.test.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionAiReportDelivery.tsx:430-445`
- Modify: `products/subscriptions/frontend/scenes/components/subscriptionStoryFixtures.ts:1-100`

**Interfaces:**

- Consumes: generated `AiQueryPlanStatusEnumApi` and `SubscriptionApi.ai_query_plan_status` from Task 2.
- Produces: `SubscriptionQueryPlanStatus({ status }: { status: AiQueryPlanStatusEnumApi | null | undefined }): JSX.Element | null`.
- Changes: `SubscriptionSummary` renders a `Query plan` definition only when `resource_type === SubscriptionResourceTypeEnumApi.AiPrompt`.

- [ ] **Step 1: Write failing status-component tests**

For each generated enum value, render the real component and assert the complete accessible label, `tabIndex="0"`, and tooltip content after pointer/mouse enter. Use `delayMs={0}` in the production tooltip so the focused test is deterministic. Add an unknown-value test using a deliberate cast and assert the component renders nothing.

Literal expected copy:

```typescript
const EXPECTED = {
  [AiQueryPlanStatusEnumApi.Frozen]:
    'Frozen query plan. PostHog will reuse these query definitions for each delivery. Date ranges, results, and the written report will still update. PostHog generates a new plan when you edit the prompt or when the query planner is updated.',
  [AiQueryPlanStatusEnumApi.NotFrozen]:
    'Query plan not frozen. No reusable plan is available yet. PostHog will freeze the plan when it can be safely reused.',
  [AiQueryPlanStatusEnumApi.PlannerUpdated]:
    'Query plan will be regenerated. The query planner changed. The next successful delivery will freeze a new plan.',
}
```

- [ ] **Step 2: Write failing summary and delivery-heading tests**

Render `SubscriptionSummary` once with an AI fixture and once with an insight fixture. Assert `Query plan` and the status image appear only for the AI resource.

Rename the delivery helper test to `.tsx`, render `ExpandedDeliveryRow` with the complete `del-ai-report` story fixture, and assert it shows `Queries` while `Generated queries` is absent.

- [ ] **Step 3: Run the frontend tests and verify RED**

Run:

```bash
flox activate -- hogli test products/subscriptions/frontend/scenes/components/SubscriptionQueryPlanStatus.test.tsx
flox activate -- hogli test products/subscriptions/frontend/scenes/components/SubscriptionSummary.test.tsx
flox activate -- hogli test products/subscriptions/frontend/scenes/components/SubscriptionAiReportDelivery.test.tsx
```

Expected: the new component/tests initially fail to compile or render because the component and summary item do not exist, and the existing heading remains `Generated queries`.

- [ ] **Step 4: Implement the focused status component**

Map each enum to a static presentation containing its icon, complete copy, and visual tone. Render a focusable wrapper with `role="img"`, `aria-label={copy}`, `tabIndex={0}`, and `data-attr={`query-plan-status-${status}`}` inside LemonUI `Tooltip`:

```tsx
<Tooltip title={copy} delayMs={0}>
  <span
    role="img"
    aria-label={copy}
    tabIndex={0}
    data-attr={`query-plan-status-${status}`}
    className="inline-flex cursor-help rounded-sm text-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
  >
    <Icon aria-hidden="true" />
  </span>
</Tooltip>
```

Use `IconPinFilled` with the normal foreground color for `frozen`, `IconPin` with `text-secondary` for `not_frozen`, and `IconRefresh` with `text-warning` for `planner_updated`. Return `null` for missing or unknown values.

- [ ] **Step 5: Integrate the summary and delivery heading**

Import `SubscriptionResourceTypeEnumApi` and `SubscriptionQueryPlanStatus`. Append this definition item inside the summary grid:

```tsx
{
  sub.resource_type === SubscriptionResourceTypeEnumApi.AiPrompt ? (
    <div>
      <dt className="text-sm text-secondary">Query plan</dt>
      <dd className="font-medium">
        <SubscriptionQueryPlanStatus status={sub.ai_query_plan_status} />
      </dd>
    </div>
  ) : null
}
```

Change only the delivery section heading from `Generated queries` to `Queries`.

- [ ] **Step 6: Add representative Storybook states**

Add `ai_query_plan_status: null` to non-AI fixtures required by the generated contract. Create three AI fixtures by spreading the complete subscription fixture and setting `resource_type`, `prompt`, and each status. Render the three real `SubscriptionSummary` components in labeled cards in one `Products/Subscriptions/Subscription summary` story so visual review covers the icons and grid without a backend.

- [ ] **Step 7: Run the frontend tests and verify GREEN**

Run the same three focused frontend commands. Expected: all status, summary visibility, accessibility, tooltip, and heading assertions pass.

- [ ] **Step 8: Commit the frontend feature**

```bash
git add products/subscriptions/frontend/scenes/components
git commit -S -m "feat(subscriptions): show frozen query plan status"
```

---

### Task 4: Verify contracts, behavior, accessibility, and layout

**Files:**

- Verify all modified files from Tasks 1-3.
- Modify only if formatting, generated-contract checks, or visual QA expose a concrete defect.

**Interfaces:**

- Consumes the complete backend/API/frontend feature.
- Produces verification evidence and a clean local branch ready for review.

- [ ] **Step 1: Run focused backend suites**

```bash
flox activate -- hogli test products/exports/backend/temporal/subscriptions/ai_subscription/test/test_spec_generator.py::TestBuildFrozenPrompt
flox activate -- hogli test ee/api/test/test_subscription.py::TestAISubscriptionAPI
```

Expected: all selected tests pass.

- [ ] **Step 2: Run focused frontend suites**

```bash
flox activate -- hogli test products/subscriptions/frontend/scenes/components/SubscriptionQueryPlanStatus.test.tsx
flox activate -- hogli test products/subscriptions/frontend/scenes/components/SubscriptionSummary.test.tsx
flox activate -- hogli test products/subscriptions/frontend/scenes/components/SubscriptionAiReportDelivery.test.tsx
```

Expected: all selected tests pass.

- [ ] **Step 3: Run static and generated checks**

```bash
flox activate -- hogli build:openapi
flox activate -- hogli lint -y
flox activate -- hogli build:frontend -y
flox activate -- hogli ci:preflight --strict --against origin/master
git diff --check
```

- [ ] **Step 4: Perform visual QA in Storybook**

Start Storybook, open the `Products/Subscriptions/Subscription summary` story, and capture the real rendered states at approximately 1280px and 390px scene widths. Verify:

- The icons are visibly distinct and aligned with the definition-list values.
- The summary grid wraps without clipping or horizontal scrolling.
- Hover reveals the complete tooltip.
- Keyboard focus is visible and the accessible label contains the complete explanation.
- The control still reads as informational, not clickable.

- [ ] **Step 5: Review the final diff and repository state**

```bash
git diff origin/master...HEAD --check
git status --short --branch
git log --show-signature --oneline origin/master..HEAD
```

Confirm there are no unrelated changes, no uncommitted generated files, and every implementation commit carries a signature block.
