# Classify workflows from their step types, in code

Whether a workflow is messaging (an email, SMS or push step, never Slack) is computed in `workflow_classification` from the workflow's step types and its `origin_product`. It is never stored as a kind or a channel list.
When a stored value is added for fast counts, it is the sorted, distinct step types (`step_types`). The rules that turn those types into channels and kinds stay in code, so changing a rule needs only a deploy, never a backfill.
Events and API rows carry the computed `kind` and `channels`, so agents and analysts never have to rebuild the rule.

## Considered options

- **Store the channels:** this was rejected because a new channel or a Slack rule change would need a backfill.
- **Store the kind:** this was rejected because `kind` also depends on `origin_product`, which a queryset `.update()` changes without passing `save()`.
