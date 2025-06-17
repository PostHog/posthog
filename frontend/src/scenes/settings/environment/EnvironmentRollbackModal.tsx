import { LemonButton, LemonCollapse, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { pluralize } from 'lib/utils'

import { environmentRollbackModalLogic, type ProjectWithEnvironments } from './environmentRollbackModalLogic'

function ModalDescription(): JSX.Element {
    return (
        <div className="space-y-2">
            <p className="mt-2">
                Thank you for participating in the environments beta! We received a bunch of great feedback from
                everyone and we've decided to rollback what is out there so we can come back with an even better
                implementation.
            </p>
            <p>
                You're seeing this because you're using multiple environments per project. As we rollback the beta we're
                moving environments back to a project-based approach, and we're offering a way to consolidate your
                environments.
            </p>
            <p className="font-bold">You will not lose any data.</p>
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
        <div className="mb-4 flex items-center gap-4 w-full">
            <div className="font-semibold min-w-0 flex-1 flex items-center gap-2">
                <UploadedLogo name={project.name} entityId={project.id} outlinedLettermark size="small" />
                <span className="truncate" title={project.name}>
                    {project.name}
                </span>
            </div>
            <LemonSelect
                value={selectedEnvironments[project.id]}
                onChange={(value) => setProjectEnvironment(project.id, value)}
                options={environmentOptions}
                className="w-[300px] flex-shrink-0"
                placeholder="Select primary environment"
            />
        </div>
    )
}

function ModalFooter(): JSX.Element {
    const { closeModal, submitEnvironmentRollback } = useActions(environmentRollbackModalLogic)
    const { isReadyToSubmit } = useValues(environmentRollbackModalLogic)

    return (
        <div className="space-y-2">
            <LemonCollapse
                className="my-2"
                panels={[
                    {
                        key: 'resources',
                        header: 'What will happen to my resources?',
                        content: (
                            <>
                                <p>
                                    For each project, all resources will be moved from your other environments into your
                                    chosen primary environment. This includes things like:
                                </p>
                                <div>
                                    <ul className="list-disc pl-8">
                                        <li>Analytics content such as saved insights and dashboard layouts</li>
                                        <li>Product tools like feature flags and their rollout configurations</li>
                                        <li>
                                            Custom definitions including event actions and behavioral tracking rules
                                        </li>
                                        <li>User research tools such as surveys and feedback forms</li>
                                        <li>Testing infrastructure like A/B experiments and their settings</li>
                                        <li>Audience segments and user cohort definitions</li>
                                        <li>Timeline annotations and important event markers</li>
                                        <li>Beta features and early access management</li>
                                    </ul>
                                </div>
                            </>
                        ),
                    },
                    {
                        key: 'data',
                        header: 'Will my data be affected?',
                        content: (
                            <>
                                <p>No.</p>
                            </>
                        ),
                    },
                ]}
            />
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
                    Separate environments
                </LemonButton>
            </div>
        </div>
    )
}

export function EnvironmentRollbackModal(): JSX.Element {
    const { isOpen, projectsWithEnvironments, currentOrganizationLoading, hiddenProjectsCount } =
        useValues(environmentRollbackModalLogic)
    const { closeModal } = useActions(environmentRollbackModalLogic)

    return (
        <LemonModal
            title="Separate environments into projects"
            description={<ModalDescription />}
            onClose={closeModal}
            isOpen={isOpen}
            width="40rem"
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
                        <>
                            {projectsWithEnvironments.map((project) => (
                                <ProjectEnvironmentSelector key={project.id} project={project} />
                            ))}
                            {hiddenProjectsCount > 0 && (
                                <div className="flex items-center gap-4 w-full opacity-50">
                                    <div className="min-w-0 flex-1 flex items-center gap-2">
                                        <div className="w-6 h-6 bg-border rounded-full flex-shrink-0" />
                                        <div className="flex-1 text-muted text-sm">
                                            + {pluralize(hiddenProjectsCount, 'project')} already using single
                                            environment
                                        </div>
                                    </div>
                                    <div className="w-[300px] h-8 bg-border rounded flex-shrink-0 flex items-center justify-center">
                                        <span className="text-muted text-xs">No action needed</span>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>

                <ModalFooter />
            </div>
        </LemonModal>
    )
}
