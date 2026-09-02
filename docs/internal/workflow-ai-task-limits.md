# Workflow AI task daily limits

Workflow-created AI tasks have two rolling 24-hour limits:

- 100 tasks per workflow
- 500 tasks across all workflows in a project

These defaults prevent a broadly matching event trigger from sustaining unbounded agent runs. The project-wide limit also prevents multiple workflows from multiplying the per-workflow allowance.

Staff can override either limit for a project in Django admin under **Team workflows configs**. Leave a value blank to use the default. Set it to zero to pause new workflow-created tasks at that scope.

Keep both limits enabled when raising capacity. Set the per-workflow limit for the expected trigger volume and retain a higher project-wide ceiling as the final spend guardrail.
