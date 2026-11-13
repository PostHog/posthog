import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'

import { oauthDeviceAuthorizeLogic } from '../oauthDeviceAuthorizeLogic'

function byName(a: { name: string }, b: { name: string }): number {
    return a.name.localeCompare(b.name)
}

export function DeviceProjectPicker(): JSX.Element {
    const { organizationId, organizations, projectId, projects, projectsLoading, projectsError } =
        useValues(oauthDeviceAuthorizeLogic)
    const { setOrganizationId, setProjectId, loadProjects } = useActions(oauthDeviceAuthorizeLogic)

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
