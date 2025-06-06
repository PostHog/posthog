import { LemonButton, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { pluralize } from 'lib/utils'

import { environmentRollbackModalLogic } from './environmentRollbackModalLogic'

function ModalDescription(): JSX.Element {
    return (
        <div>
            <p className="mb-2">
                All the insights currently present on your environments will be migrated to a single project. Please
                choose which one you want this single environment to be.
            </p>
            <p className="mb-2">
                We recommend that you select your <b>production</b> environment.
            </p>
        </div>
    )
}

function ModalFooter(): JSX.Element {
    const { closeModal, submitEnvironmentRollback } = useActions(environmentRollbackModalLogic)
    const { projectsWithEnvironments, hiddenProjectsCount, selectedEnvironmentId } =
        useValues(environmentRollbackModalLogic)

    return (
        <div className="space-y-2">
            {hiddenProjectsCount > 0 && (
                <div className="text-muted text-sm">
                    {pluralize(hiddenProjectsCount, 'project')} with only 1 environment found, these can be safely
                    ignored.
                </div>
            )}
            <LemonBanner type="warning">
                This action cannot be undone. Please make sure you select the correct environment.
            </LemonBanner>
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={closeModal}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    status="danger"
                    onClick={submitEnvironmentRollback}
                    disabled={projectsWithEnvironments.length === 0 || !selectedEnvironmentId}
                >
                    Migrate environments
                </LemonButton>
            </div>
        </div>
    )
}

export function EnvironmentRollbackModal(): JSX.Element {
    const { isOpen, projectsWithEnvironments, currentOrganizationLoading, selectedEnvironmentId } =
        useValues(environmentRollbackModalLogic)
    const { closeModal, setSelectedEnvironmentId } = useActions(environmentRollbackModalLogic)

    const selectOptions = projectsWithEnvironments.map((project) => ({
        title: `Project: ${project.name}`,
        options: project.environments.map((env) => ({
            value: env.id,
            label: env.name,
        })),
    }))

    return (
        <LemonModal
            title="Migrate to single environment"
            description={<ModalDescription />}
            onClose={closeModal}
            isOpen={isOpen}
            width={600}
        >
            <div className="space-y-4">
                <div className="space-y-2 flex justify-center items-center">
                    {currentOrganizationLoading ? (
                        <div className="p-4">
                            <Spinner />
                        </div>
                    ) : projectsWithEnvironments.length === 0 ? (
                        <div className="text-muted">No projects with multiple environments found</div>
                    ) : (
                        <LemonSelect
                            className="py-6"
                            value={selectedEnvironmentId}
                            onChange={(value) => setSelectedEnvironmentId(value)}
                            options={selectOptions}
                            placeholder="Select an environment"
                        />
                    )}
                </div>

                <ModalFooter />
            </div>
        </LemonModal>
    )
}
