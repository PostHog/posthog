import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { environmentRollbackModalLogic, ProjectWithEnvironments, Team } from './environmentRollbackModalLogic'

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

interface ProjectEnvironmentsProps {
    project: ProjectWithEnvironments
}

function ProjectEnvironments({ project }: ProjectEnvironmentsProps): JSX.Element {
    const { selectedEnvironmentId } = useValues(environmentRollbackModalLogic)
    const { setSelectedEnvironmentId } = useActions(environmentRollbackModalLogic)

    return (
        <div className="border rounded p-4">
            <h4 className="mb-2">Project: {project.name}</h4>
            <div className="space-y-2">
                {project.environments.map((env: Team) => (
                    <div key={env.id} className="flex items-center gap-2">
                        <div className="flex items-center">
                            <input
                                type="radio"
                                checked={selectedEnvironmentId === env.id}
                                onChange={() => setSelectedEnvironmentId(env.id)}
                                id={`env-${env.id}`}
                                className="mr-2"
                            />
                            <label htmlFor={`env-${env.id}`}>{env.name}</label>
                        </div>
                    </div>
                ))}
            </div>
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
                    {hiddenProjectsCount} project{hiddenProjectsCount !== 1 ? 's' : ''} with only 1 environment found,
                    these can be safely ignored
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
    const { isOpen, projectsWithEnvironments, currentOrganizationLoading } = useValues(environmentRollbackModalLogic)
    const { closeModal } = useActions(environmentRollbackModalLogic)

    return (
        <LemonModal
            title="Migrate to single environment"
            description={<ModalDescription />}
            onClose={closeModal}
            isOpen={isOpen}
            width={600}
        >
            <div className="space-y-4">
                <div className="space-y-2">
                    {currentOrganizationLoading ? (
                        <div className="flex justify-center items-center p-4">
                            <Spinner />
                        </div>
                    ) : projectsWithEnvironments.length === 0 ? (
                        <div className="flex justify-center items-center p-4 text-muted">
                            No projects with multiple environments found
                        </div>
                    ) : (
                        projectsWithEnvironments.map((project: ProjectWithEnvironments) => (
                            <ProjectEnvironments key={project.id} project={project} />
                        ))
                    )}
                </div>

                <ModalFooter />
            </div>
        </LemonModal>
    )
}
