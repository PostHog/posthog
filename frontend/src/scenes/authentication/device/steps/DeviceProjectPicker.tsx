import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { InlineCreateForm } from 'scenes/authentication/shared/InlineCreateForm'
import { organizationLogic } from 'scenes/organizationLogic'

import { AvailableFeature } from '~/types'

import { oauthDeviceAuthorizeLogic } from '../oauthDeviceAuthorizeLogic'

function byName(a: { name: string }, b: { name: string }): number {
    return a.name.localeCompare(b.name)
}

export function DeviceProjectPicker(): JSX.Element {
    const {
        organizationId,
        organizations,
        projectId,
        projects,
        projectsLoading,
        projectsError,
        showCreateProject,
        creatingProject,
    } = useValues(oauthDeviceAuthorizeLogic)
    const { setOrganizationId, setProjectId, loadProjects, setShowCreateProject, createProject } =
        useActions(oauthDeviceAuthorizeLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { currentOrganization, currentOrganizationProjectCount, projectCreationForbiddenReason } =
        useValues(organizationLogic)
    // Plan and role data is only loaded for the current organization, so the backend decides for any other one.
    const isCurrentOrganization = organizationId === currentOrganization?.id

    const startCreatingProject = (): void => {
        if (!isCurrentOrganization) {
            setShowCreateProject(true)
            return
        }
        guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, () => setShowCreateProject(true), {
            currentUsage: currentOrganizationProjectCount,
        })
    }

    return (
        <>
            <LemonField.Pure label="Organization">
                <LemonInputSelect
                    mode="single"
                    fullWidth
                    data-attr="oauth-device-organization"
                    placeholder="Search for an organization"
                    value={organizationId ? [organizationId] : []}
                    onChange={([key]) => setOrganizationId(key ?? null)}
                    options={[...organizations].sort(byName).map((organization) => ({
                        key: organization.id,
                        label: organization.name,
                    }))}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Project" help="The login only works in this project.">
                {showCreateProject ? (
                    <InlineCreateForm
                        label="New project name"
                        placeholder="e.g. My App"
                        loading={creatingProject}
                        onSubmit={createProject}
                        onCancel={() => setShowCreateProject(false)}
                    />
                ) : (
                    <div className="flex items-center gap-2">
                        <div className="flex-1 min-w-0">
                            <LemonInputSelect
                                mode="single"
                                fullWidth
                                data-attr="oauth-device-project"
                                placeholder={organizationId ? 'Search for a project' : 'Select an organization first'}
                                value={projectId === null ? [] : [String(projectId)]}
                                onChange={([key]) => setProjectId(key ? Number(key) : null)}
                                disabled={!organizationId}
                                loading={projectsLoading}
                                virtualized={projects.length > 100}
                                options={[...projects].sort(byName).map((project) => ({
                                    key: String(project.id),
                                    label: project.name,
                                }))}
                            />
                        </div>
                        <LemonButton
                            className="shrink-0"
                            type="secondary"
                            icon={<IconPlus />}
                            tooltip="New project"
                            data-attr="oauth-device-new-project"
                            disabledReason={
                                !organizationId
                                    ? 'Select an organization first'
                                    : isCurrentOrganization
                                      ? (projectCreationForbiddenReason ?? undefined)
                                      : undefined
                            }
                            onClick={startCreatingProject}
                        />
                    </div>
                )}
            </LemonField.Pure>
            {projectsError && organizationId && (
                <AuthBanner variant="danger">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>Couldn't load the projects. {projectsError}</span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => loadProjects(organizationId)}
                            loading={projectsLoading}
                            data-attr="oauth-device-retry-projects"
                        >
                            Try again
                        </LemonButton>
                    </div>
                </AuthBanner>
            )}
        </>
    )
}
