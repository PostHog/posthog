# Tasks-agent worker deployments

`container-images-cd.yml` dispatches the tasks-agent Temporal worker deployment when the commit changes a path in `check_changes_tasks_agent_temporal_worker`.

The filter includes `posthog/temporal/oauth.py`. The worker imports this shared module to decode MCP scope payloads and mint sandbox tokens, so OAuth changes must deploy to the worker alongside their callers. Deploying only a caller can leave the worker decoding a new payload with an older scope type.

Changes to `container-images-cd.yml` also trigger the tasks-agent deployment. This lets a deployment-filter correction refresh the worker without an unrelated application change. The existing production deployment gate still applies.

When changing shared worker dependencies, check this filter as well as the product paths. To verify a rollout was requested, inspect the **Trigger Tasks Agent Temporal worker cloud deployment** step in the Container Images CD run. A successful image build alone does not prove that this worker received a deployment dispatch.
