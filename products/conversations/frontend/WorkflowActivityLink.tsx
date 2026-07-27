import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { workflowsLogic } from 'products/workflows/frontend/Workflows/workflowsLogic'

// Renders the workflow that made a ticket change as a link, resolving the current name from the
// workflow itself (by id) rather than from the activity-log payload — the name is never trusted
// from the caller-supplied header, so it can't be spoofed. Falls back to a generic label when the
// workflow can't be resolved (e.g. it was deleted).
export function WorkflowActivityLink({ id }: { id: string }): JSX.Element {
    const { workflows, hasLoadedWorkflows } = useValues(workflowsLogic)
    const { loadWorkflows } = useActions(workflowsLogic)

    useOnMountEffect(() => {
        if (!hasLoadedWorkflows) {
            loadWorkflows()
        }
    })

    const name = workflows.find((workflow) => workflow.id === id)?.name

    return (
        <strong>
            <Link to={urls.workflow(id, 'workflow')}>{name || 'A workflow'}</Link>
        </strong>
    )
}
