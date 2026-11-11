import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CohortBlockedAction, cohortBlockingWorkflowsModalLogic } from './cohortBlockingWorkflowsModalLogic'

const BLOCKING_COPY: Record<CohortBlockedAction, string> = {
    delete: 'These workflows trigger on this cohort or branch on it. Remove the cohort from each workflow, or disable the workflow, then delete the cohort.',
    edit: 'These workflows trigger on this cohort or branch on it, so its criteria are locked. Changing them would send current members through these workflows again. Remove the cohort from each workflow, or disable the workflow, then save your change.',
    view: "These workflows trigger on this cohort or branch on it, so the cohort is locked. You can't delete it or change its criteria. Remove the cohort from each workflow, or disable the workflow, to unlock it.",
}

export function CohortBlockingWorkflowsModal(): JSX.Element {
    const { blocking } = useValues(cohortBlockingWorkflowsModalLogic)
    const { closeBlockingWorkflowsModal } = useActions(cohortBlockingWorkflowsModalLogic)
    const hiddenCount = blocking?.workflows.hidden ?? 0
    // The API caps the list it returns, so some workflows the person can view may not be listed.
    const unlistedCount = blocking ? blocking.workflows.total - hiddenCount - blocking.workflows.results.length : 0

    return (
        <LemonModal
            isOpen={!!blocking}
            onClose={closeBlockingWorkflowsModal}
            title="This cohort is used by active workflows"
            width={480}
            footer={
                <LemonButton type="secondary" onClick={closeBlockingWorkflowsModal}>
                    Close
                </LemonButton>
            }
        >
            {blocking && (
                <div className="flex flex-col gap-y-3" data-attr="cohort-blocking-workflows">
                    <p className="mb-0">{BLOCKING_COPY[blocking.action]}</p>
                    {blocking.workflows.results.length > 0 && (
                        <ul className="list-disc pl-4 mb-0">
                            {blocking.workflows.results.map((workflow) => (
                                <li key={workflow.id}>
                                    <Link
                                        to={urls.workflow(workflow.id, 'workflow')}
                                        onClick={closeBlockingWorkflowsModal}
                                        data-attr="cohort-blocking-workflow-link"
                                    >
                                        {workflow.name || 'Untitled workflow'}
                                    </Link>
                                </li>
                            ))}
                            {unlistedCount > 0 && <li className="text-secondary">and {unlistedCount} more</li>}
                        </ul>
                    )}
                    {hiddenCount > 0 && (
                        <p className="mb-0 text-secondary">
                            {hiddenCount === 1
                                ? "1 more workflow uses this cohort, but you don't have access to it. Ask someone who can edit it to remove the cohort."
                                : `${hiddenCount} more workflows use this cohort, but you don't have access to them. Ask someone who can edit them to remove the cohort.`}
                        </p>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
