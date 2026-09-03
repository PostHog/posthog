# Workflow AI task daily limits

Workflow-created AI tasks have two rolling 24-hour limits:

- 100 tasks per workflow
- 500 tasks across all workflows in a project

These defaults prevent a broadly matching event trigger from sustaining unbounded agent runs. The project-wide limit also prevents multiple workflows from multiplying the per-workflow allowance.

Staff can override either limit for a project in Django admin under **Team workflows configs**. Leave a value blank to use the default. Set it to zero to pause new workflow-created tasks at that scope.

Keep both limits enabled when raising capacity. Set the per-workflow limit for the expected trigger volume and retain a higher project-wide ceiling as the final spend guardrail.

## Waiting for the task to finish

A workflow run pauses at an AI task step or a scout step until the run it started reaches a terminal status.
The next step then sees the step result: the task or run id, `status` (`completed`, `failed` or `cancelled`), and a capped `final_message` (tasks) or `summary` (scouts), plus `pr_urls` or `error_message` when present.
A failed or cancelled run fails the step, and the step's `on_error` setting decides whether the workflow continues.

A template asks for the wait by returning an `await` object next to its result, for example `{ 'id': ..., 'run_id': ..., 'await': { 'max_wait': '190m', 'label': 'task' } }`.
`max_wait` is set by the template's author, never by the workflow author, and the engine caps it at 24 hours.
The task template uses 190 minutes and the scout template 35 minutes: each product's own runtime cap plus slack, so the product's own timeout wake lands before the step's deadline.
A step that reaches its deadline without a wake fails with a timeout.
The wake arrives through the `$workflow_step_resume` internal event, keyed on the step's idempotency key, so any template that dispatches a run its owner can report on can use the same path.
`CDP_HOGFLOW_AWAITED_STEPS_ENABLED` on the plugin server turns the wait on; leave it off until the API that emits the wake is deployed.
A task that ends through the agent's `finish` tool completes a few seconds before its final message is saved.
The step waits for that message (up to 30 seconds) rather than continuing with an empty one.
