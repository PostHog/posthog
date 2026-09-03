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

The wait is bounded by the product's own runtime cap: 3 hours 10 minutes for tasks and 35 minutes for scouts.
A step that reaches the cap without a result fails with a timeout.
The wake arrives through the `$workflow_step_resume` internal event, keyed on the step's idempotency key.
`CDP_HOGFLOW_AWAIT_TASK_COMPLETION` on the plugin server turns the wait on; leave it off until the API that emits the wake is deployed.
A task that ends through the agent's `finish` tool completes a few seconds before its final message is saved.
The step waits for that message (up to 30 seconds) rather than continuing with an empty one.
