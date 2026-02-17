import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { JSSnippet, JSSnippetV2 as JSSnippetV2Component } from 'lib/components/JSSnippet'
import { getPublicSupportSnippet } from 'lib/components/Support/supportLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { debounce, inStorybook, inStorybookTestRunner } from 'lib/utils'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { BusinessModelConfig } from './BusinessModelConfig'
import { TimezoneConfig } from './TimezoneConfig'
import { WeekStartConfig } from './WeekStartConfig'

export function TeamDisplayName({ updateInline = false }: { updateInline?: boolean }): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [name, setName] = useState(currentTeam?.name || '')

    const debouncedUpdateCurrentTeam = useMemo(() => debounce(updateCurrentTeam, 500), [updateCurrentTeam])
    const handleChange = (value: string): void => {
        setName(value)
        if (updateInline) {
            debouncedUpdateCurrentTeam({ name: value })
        }
    }

    return (
        <div className="deprecated-space-y-4 max-w-160">
            <LemonInput value={name} onChange={handleChange} />
            {!updateInline && (
                <LemonButton
                    type="primary"
                    onClick={() => updateCurrentTeam({ name })}
                    disabled={!name || !currentTeam || name === currentTeam.name}
                    loading={currentTeamLoading}
                >
                    Rename project
                </LemonButton>
            )}
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

export function WebSnippetV2(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return currentTeamLoading && !currentTeam ? (
        <div className="deprecated-space-y-4">
            <LemonSkeleton className="w-1/2 h-4" />
            <LemonSkeleton repeat={3} />
        </div>
    ) : (
        <JSSnippetV2Component />
    )
}

function DebugInfoPanel(): JSX.Element | null {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { preflight, preflightLoading } = useValues(preflightLogic)

    const region = preflight?.region
    const anyLoading = preflightLoading || currentOrganizationLoading || currentTeamLoading
    const hasRequiredInfo = region && currentOrganization && currentTeam

    if (!hasRequiredInfo && !anyLoading) {
        return null
    }

    if (inStorybookTestRunner() || inStorybook()) {
        // this data changes e.g. when session id changes, so it flaps in visual regression tests
        // so...
        return null
    }

    return (
        <div className="flex-1 max-w-full">
            <h3 id="debug-info" className="min-w-[25rem]">
                Debug information
            </h3>
            <p>Include this snippet when creating an issue (feature request or bug report) on GitHub.</p>
            {anyLoading ? (
                <LemonSkeleton repeat={2} active={true} />
            ) : (
                <CodeSnippet compact thing="debug info">
                    {getPublicSupportSnippet(region, currentOrganization, currentTeam, false)}
                </CodeSnippet>
            )}
        </div>
    )
}

export function TeamVariables(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)

    const { preflight } = useValues(preflightLogic)

    const region = preflight?.region

    const RESET_CONFIRMATION = 'RESET'

    const openDialog = (): void => {
        LemonDialog.openForm({
            maxWidth: 480,
            title: 'Reset project API key?',
            description:
                'This will immediately invalidate your current API key. Any apps, websites, or services using it will stop sending data to PostHog until you update them with the new key. This action cannot be undone.',
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
                children: 'Reset API key',
            },
            onSubmit: () => {
                resetToken()
            },
        })
    }

    return (
        <div className="space-y-4 max-w-200">
            <div className="border rounded p-4 space-y-3 bg-bg-light">
                <LemonLabel className="mb-0">Project API key</LemonLabel>
                <CodeSnippet
                    compact
                    thing="project API key"
                    actions={
                        isTeamTokenResetAvailable ? (
                            <LemonButton
                                icon={<IconRefresh />}
                                noPadding
                                onClick={openDialog}
                                tooltip="Reset API key"
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

            <DebugInfoPanel />
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
        />
    )
}
