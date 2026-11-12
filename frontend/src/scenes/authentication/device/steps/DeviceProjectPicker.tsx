import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'

import { oauthDeviceAuthorizeLogic } from '../oauthDeviceAuthorizeLogic'

export function DeviceProjectPicker(): JSX.Element {
    const { organizationId, organizations, projectId, projects, projectsLoading, projectsError } =
        useValues(oauthDeviceAuthorizeLogic)
    const { setOrganizationId, setProjectId, loadProjects } = useActions(oauthDeviceAuthorizeLogic)

    return (
        <>
            <LemonField.Pure label="Organization">
                <LemonSelect
                    data-attr="oauth-device-organization"
                    placeholder="Select an organization"
                    value={organizationId}
                    onChange={setOrganizationId}
                    options={organizations.map((organization) => ({
                        label: organization.name,
                        value: organization.id,
                    }))}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Project" help="The login only works in this project.">
                <LemonSelect
                    data-attr="oauth-device-project"
                    placeholder="Select a project"
                    value={projectId}
                    onChange={setProjectId}
                    disabledReason={organizationId ? undefined : 'Select an organization first'}
                    loading={projectsLoading}
                    options={projects.map((project) => ({ label: project.name, value: project.id }))}
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
