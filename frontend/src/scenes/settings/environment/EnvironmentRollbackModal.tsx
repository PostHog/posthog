import { LemonButton, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { pluralize } from 'lib/utils'

import { environmentRollbackModalLogic, type ProjectWithEnvironments } from './environmentRollbackModalLogic'

function ModalDescription(): JSX.Element {
    return (
        <div className="space-y-2">
            <p className="mt-2">
                We noticed you're using multiple environments per project. As we're moving towards a simpler
                project-based approach, we're offering a way to consolidate your environments.
            </p>
            <p>For each project below, select which environment you'd like to keep as the primary one.</p>
            <p>The following data will be migrated from other environments to your selected one:</p>
            <div>
                <ul className="list-disc pl-8">
                    <li>Insights & Dashboards</li>
                    <li>Feature Flags</li>
                    <li>Actions & Surveys</li>
                    <li>Experiments</li>
                    <li>Cohorts</li>
                </ul>
            </div>
            <p className="text-sm text-muted">
                While this change is optional now, we recommend completing it within the next 2 months to ensure a
                smooth transition when multi-environment projects are discontinued.
            </p>
        </div>
    )
}

function ProjectEnvironmentSelector({ project }: { project: ProjectWithEnvironments }): JSX.Element {
    const { selectedEnvironments } = useValues(environmentRollbackModalLogic)
    const { setProjectEnvironment } = useActions(environmentRollbackModalLogic)

    const environmentOptions = project.environments.map((env) => ({
        value: env.id,
        label: env.name,
    }))

    return (
        <div className="mb-4">
            <div className="font-semibold mb-2">Project: {project.name}</div>
            <LemonSelect
                value={selectedEnvironments[project.id]}
                onChange={(value) => setProjectEnvironment(project.id, value)}
                options={environmentOptions}
                className="w-[250px]"
                placeholder="Select primary environment"
            />
        </div>
    )
}

function ModalFooter(): JSX.Element {
    const { closeModal, submitEnvironmentRollback } = useActions(environmentRollbackModalLogic)
    const { hiddenProjectsCount, isReadyToSubmit } = useValues(environmentRollbackModalLogic)

    return (
        <div className="space-y-2">
            {hiddenProjectsCount > 0 && (
                <div className="text-muted text-sm">
                    {pluralize(hiddenProjectsCount, 'project')} already using a single environment will not be affected.
                </div>
            )}
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={closeModal}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    status="danger"
                    onClick={submitEnvironmentRollback}
                    disabled={!isReadyToSubmit}
                >
                    Consolidate environments
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
            title="Consolidate project environments"
            description={<ModalDescription />}
            onClose={closeModal}
            isOpen={isOpen}
            width="large"
        >
            <div className="space-y-4">
                <div className="flex flex-col items-center gap-2">
                    {currentOrganizationLoading ? (
                        <div className="p-4">
                            <Spinner />
                        </div>
                    ) : projectsWithEnvironments.length === 0 ? (
                        <div className="text-muted">No projects with multiple environments found</div>
                    ) : (
                        projectsWithEnvironments.map((project) => (
                            <ProjectEnvironmentSelector key={project.id} project={project} />
                        ))
                    )}
                </div>

                <ModalFooter />
            </div>
        </LemonModal>
    )
}
