import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { featureFlagDeleteInProjectsLogic } from './featureFlagDeleteInProjectsLogic'
import { FeatureFlagLogicProps } from './featureFlagLogic'

export function FeatureFlagDeleteInProjectsResultModal({ id }: FeatureFlagLogicProps): JSX.Element | null {
    const logic = featureFlagDeleteInProjectsLogic({ id })
    const { deleteInProjectsResult, deleteInProjectsResultVisible, projectNamesById, currentFlagDeleted } =
        useValues(logic)
    const { closeDeleteInProjectsResult } = useActions(logic)

    if (!deleteInProjectsResult || !deleteInProjectsResultVisible) {
        return null
    }

    const { deleted, failed } = deleteInProjectsResult
    const projectName = (projectId: number): string => projectNamesById[projectId] ?? `Project ${projectId}`

    return (
        <LemonModal
            isOpen
            onClose={closeDeleteInProjectsResult}
            title="Delete in projects"
            width={600}
            footer={
                <LemonButton type="primary" onClick={closeDeleteInProjectsResult}>
                    {currentFlagDeleted ? 'Go to feature flags' : 'Done'}
                </LemonButton>
            }
        >
            <div className="space-y-4">
                {deleted.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-success font-medium">
                            <IconCheck className="text-lg" />
                            <span>Deleted in {pluralize(deleted.length, 'project')}</span>
                        </div>
                        <ul className="list-none pl-6 space-y-1">
                            {deleted.map(({ project_id }) => (
                                <li key={project_id} className="text-sm text-muted">
                                    {projectName(project_id)}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
                {failed.length > 0 && (
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-danger font-medium">
                            <IconX className="text-lg" />
                            <span>Not deleted in {pluralize(failed.length, 'project')}</span>
                        </div>
                        <ul className="list-none pl-6 space-y-1">
                            {failed.map(({ project_id, error_message }) => (
                                <li key={project_id} className="text-sm">
                                    <span className="text-muted">{projectName(project_id)}:</span>
                                    <span className="text-muted-alt"> {error_message}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
