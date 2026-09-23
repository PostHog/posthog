import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { JSSnippet } from 'lib/components/JSSnippet'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { isProjectNameTaken } from 'scenes/project/isProjectNameTaken'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { BusinessModelConfig } from './BusinessModelConfig'
import { TimezoneConfig } from './TimezoneConfig'
import { WeekStartConfig } from './WeekStartConfig'

const NAME_TAKEN_REASON = 'There is already a project with this name in this organization. Choose a different name.'

export function TeamDisplayName(): JSX.Element {
    const { currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentProject } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const [name, setName] = useState(currentProject?.name || '')
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    // A rename patches the project, so the uniqueness rule applies to the project's name. That can
    // differ from the environment's name, which is what `teamLogic` holds.
    const trimmedName = name.trim()
    const nameTaken = isProjectNameTaken(trimmedName, currentOrganization?.projects, {
        excludeProjectId: currentProject?.id,
        currentName: currentProject?.name,
    })
    const renameDisabledReason =
        restrictedReason ||
        (!trimmedName && 'Enter a name') ||
        (!currentProject && 'Loading the project') ||
        (trimmedName === currentProject?.name && "This is already the project's name") ||
        (nameTaken && NAME_TAKEN_REASON) ||
        null

    return (
        <div className="deprecated-space-y-4 max-w-160">
            <LemonField.Pure error={nameTaken ? NAME_TAKEN_REASON : undefined}>
                <LemonInput value={name} onChange={setName} disabledReason={restrictedReason} />
            </LemonField.Pure>
            <LemonButton
                type="primary"
                onClick={() => updateCurrentTeam({ name: trimmedName })}
                disabledReason={renameDisabledReason}
                loading={currentTeamLoading}
            >
                Rename project
            </LemonButton>
        </div>
    )
}

export function WebSnippet(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return currentTeamLoading && !currentTeam ? (
        <div className="deprecated-space-y-4">
            <LemonSkeleton className="w-1/2 h-4" />
            <LemonSkeleton repeat={3} />
        </div>
    ) : (
        <JSSnippet />
    )
}

export function TeamVariables(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const { preflight } = useValues(preflightLogic)

    const region = preflight?.region

    const RESET_CONFIRMATION = 'RESET'

    const openDialog = (): void => {
        LemonDialog.openForm({
            maxWidth: 480,
            title: 'Reset project token?',
            description:
                'This will immediately invalidate your current project token. Any apps, websites, or services using it will stop sending data to PostHog until you update them with the new token. This action cannot be undone.',
            initialValues: { confirmation: '' },
            content: (
                <LemonField name="confirmation">
                    <LemonInput
                        placeholder={`Type "${RESET_CONFIRMATION}" to confirm`}
                        autoFocus
                        data-attr="reset-api-key-confirmation-input"
                    />
                </LemonField>
            ),
            errors: {
                confirmation: (value: string) =>
                    (value || '').toUpperCase() !== RESET_CONFIRMATION
                        ? `Type "${RESET_CONFIRMATION}" to confirm`
                        : undefined,
            },
            primaryButtonProps: {
                status: 'danger',
                children: 'Reset token',
            },
            onSubmit: () => {
                resetToken()
            },
        })
    }

    return (
        <div className="space-y-4 max-w-200">
            <div className="border rounded p-4 space-y-3 bg-bg-light">
                <LemonLabel className="mb-0">Project token</LemonLabel>
                <CodeSnippet
                    compact
                    thing="project token"
                    actions={
                        isTeamTokenResetAvailable ? (
                            <LemonButton
                                icon={<IconRefresh />}
                                disabledReason={restrictedReason}
                                noPadding
                                onClick={openDialog}
                                tooltip="Reset token"
                            />
                        ) : undefined
                    }
                >
                    {currentTeam?.api_token || ''}
                </CodeSnippet>
                <p className="text-muted text-xs mb-0">
                    Write-only key for use in <Link to="https://posthog.com/docs/libraries">client libraries</Link>.
                    Safe to use in public apps.
                </p>
            </div>

            <div className="flex gap-4 flex-wrap">
                <div className="border rounded p-4 space-y-3 bg-bg-light flex-1 min-w-60">
                    <LemonLabel className="mb-0">Project ID</LemonLabel>
                    <CodeSnippet compact thing="project ID">
                        {String(currentTeam?.id || '')}
                    </CodeSnippet>
                    <p className="text-muted text-xs mb-0">
                        Use this ID in the <Link to="https://posthog.com/docs/api">PostHog API</Link>.
                    </p>
                </div>
                {region ? (
                    <div className="border rounded p-4 space-y-3 bg-bg-light flex-1 min-w-60">
                        <LemonLabel className="mb-0">Region</LemonLabel>
                        <CodeSnippet compact thing="project region">
                            {`${region} Cloud`}
                        </CodeSnippet>
                        <p className="text-muted text-xs mb-0">Where your PostHog data is hosted.</p>
                    </div>
                ) : null}
            </div>
        </div>
    )
}

export function TeamTimezone({ displayWarning = true }: { displayWarning?: boolean }): JSX.Element {
    return (
        <div className="flex flex-col sm:flex-row gap-8">
            <div className="flex flex-col gap-2 flex-1 max-w-120">
                <LemonLabel id="timezone">Time zone</LemonLabel>
                <TimezoneConfig displayWarning={displayWarning} />
            </div>
            <div className="flex flex-col gap-2">
                <LemonLabel id="timezone">Week starts on</LemonLabel>
                <WeekStartConfig displayWarning={displayWarning} />
            </div>
        </div>
    )
}

export function TeamBusinessModel(): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <LemonLabel id="business-model">Business model</LemonLabel>
            <BusinessModelConfig />
        </div>
    )
}

export function TeamAuthorizedURLs(): JSX.Element {
    // In Storybook, allow editing by default since we don't have full app context
    const canEdit =
        inStorybook() || inStorybookTestRunner()
            ? true
            : userHasAccess(AccessControlResourceType.WebAnalytics, AccessControlLevel.Editor)

    return (
        <AuthorizedUrlList
            type={AuthorizedUrlListType.WEB_ANALYTICS}
            allowWildCards={false}
            allowAdd={canEdit}
            allowDelete={canEdit}
            displaySuggestions={canEdit}
        />
    )
}
