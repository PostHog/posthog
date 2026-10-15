# Workflow AI task daily limits

Workflow-created AI tasks have two rolling 24-hour limits:

- 100 tasks per workflow
- 500 tasks across all workflows in a project

These defaults prevent a broadly matching event trigger from sustaining unbounded agent runs. The project-wide limit also prevents multiple workflows from multiplying the per-workflow allowance.

A project admin sets either limit in **Settings → Workflows → AI task limits**, up to 5x the default: 500 per workflow and 2,500 per project. Leave a value blank to use the default. Set it to zero to pause new workflow-created tasks at that scope.

Staff raise a project past those ceilings in Django admin under **Team workflows configs**, which does not use the API serializer that holds them.

When a limit blocks task creation, the Create AI task step records the API reason as an error. The workflow then follows the step's `on_error` configuration.

Keep both limits enabled when raising capacity. Set the per-workflow limit for the expected trigger volume and retain a higher project-wide ceiling as the final spend guardrail.

## Waiting for the task to finish

A workflow run pauses at an AI task step or a scout step until the run it started reaches a terminal status.
After success, the next step sees the dispatch IDs, `status: completed`, and a capped `final_message` (tasks) or `summary` (scouts). The result also includes `pr_urls` when present.
A failed or cancelled run fails the step. The step's `on_error` setting decides whether the workflow continues.
With `on_error: continue`, the next step sees the dispatch IDs, the terminal `status`, and `error_message`, so a condition step can route a failed run to a notification.

### Fields the agent returns

An AI task step can hand fields the agent produced to later steps.
The author adds an output variable mapping with the result path `output.<name>`, for example `output.verdict` into the variable `verdict`.
The engine sends these fields with the create request as `output_fields`, a name to type map typed after the workflow variable (`string`, `number`, or `boolean`), with at most 20 fields.
The tasks API builds the schema from that map. Field names are identifiers, and the names the task result uses for itself (`final_message`, `pr_urls` and the other bookkeeping keys) are refused.
The agent runtime enforces the schema at the end of the run, and the resume result carries the fields under `output`, ahead of the final message.
The agent prompt names the fields and their budget: each text field is capped at 1500 characters, and the fields share the 4096 byte step result with the final message, fields first.
When the agent finishes without output that matches the fields, or a field was cut to fit the step result, the step still completes.
The resume result carries `warnings`, the engine writes each one to the run log at `warn` level and counts the resume in `cdp_hogflow_awaited_step_resumed_with_warnings`, and the unmatched variables stay null.

A template asks for the wait by returning an `await` object next to its result, for example `{ 'id': ..., 'run_id': ..., 'await': { 'max_wait': '190m', 'label': 'task' } }`.
`max_wait` is set by the template's author, never by the workflow author, and the engine caps it at 24 hours.
The task template uses 190 minutes and the scout template 35 minutes: each product's own runtime cap plus slack, so the product's own timeout wake lands before the step's deadline.
A step that reaches its deadline without a wake fails with a timeout.
The wake is keyed on the step's idempotency key, so any template that dispatches a run its owner can report on can use the same path.
With `WORKFLOWS_STEP_RESUME_JWT_SECRET` provisioned on Django and the plugin server, the process that marks the run terminal posts the wake to the CDP API's `workflow_steps/resume` route with a scoped JWT.
Without the key, or when the API cannot be reached, the wake is the `$workflow_step_resume` internal event, consumed by the subscription matcher.
Provision the key only after the release that carries the route is live on the plugin server, and on every Django process that marks a run terminal: web, Celery and Temporal.
`CDP_HOGFLOW_AWAITED_STEPS_ENABLED` on the plugin server enables new waits. Existing waits still receive their results when this flag is off.
A wake that lands while the step is still dispatching cannot be applied, because the worker owns the job state until it parks. The `cdp_hogflow_step_resume` counter reports these as `job_running`.
A run takes seconds to minutes to finish, so a wake meets this only as the duplicate of one already taken; the route answers 409 and the caller drops it.
Leave the flag off until the API that emits the wake is deployed.
A task that ends through the agent's `finish` tool completes a few seconds before its final message is saved.
The step waits for that message (up to 30 seconds) rather than continuing with an empty one.
