import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { JSSnippet, JSSnippetV2 } from 'lib/components/JSSnippet'
import { getPublicSupportSnippet } from 'lib/components/Support/supportLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { debounce, inStorybook, inStorybookTestRunner } from 'lib/utils'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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

    return (
        <>
            <p>
                PostHog's configurable web snippet allows you to (optionally) autocapture events, record user sessions,
                and more with no extra work. Place the following snippet in your website's HTML, ideally just above the{' '}
                <code>{'</head>'}</code> tag.
            </p>
            <p>
                For more guidance, including on identifying users,{' '}
                <Link to="https://posthog.com/docs/libraries/js">see PostHog Docs</Link>.
            </p>
            {currentTeamLoading && !currentTeam ? (
                <div className="deprecated-space-y-4">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton repeat={3} />
                </div>
            ) : (
                <JSSnippet />
            )}

            <FlaggedFeature flag="remote-config">
                <h3 className="mt-4 flex items-center gap-2">
                    Web Snippet V2 <LemonTag type="warning">Experimental</LemonTag>
                </h3>
                <p>
                    The V2 version of the snippet is more advanced and includes your project config automatically along
                    with the PostHog JS code. This generally leads to faster load times and fewer calls needed before
                    the SDK is fully functional.
                </p>
                {currentTeamLoading && !currentTeam ? (
                    <div className="deprecated-space-y-4">
                        <LemonSkeleton className="w-1/2 h-4" />
                        <LemonSkeleton repeat={3} />
                    </div>
                ) : (
                    <JSSnippetV2 />
                )}
            </FlaggedFeature>
        </>
    )
}

export function Bookmarklet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <p>Need to test PostHog on a live site without changing any code?</p>
            <p>
                Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on and
                click it. This will enable our tracking, on the currently loaded page only. The data will show up in
                this project.
            </p>
            <div>{isAuthenticatedTeam(currentTeam) && <JSBookmarklet team={currentTeam} />}</div>
        </>
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
        <>
            <p>
                The timezone config affect how PostHog displays, buckets, and filters time-series data.{' '}
                {displayWarning && 'You may need to refresh insights for new settings to apply.'}
            </p>
            <div className="flex flex-col sm:flex-row gap-8">
                <div className="flex flex-col gap-2 flex-1 max-w-160">
                    <LemonLabel id="timezone">Time zone</LemonLabel>
                    <TimezoneConfig displayWarning={displayWarning} />
                </div>
                <div className="flex flex-col gap-2">
                    <LemonLabel id="timezone">Week starts on</LemonLabel>
                    <WeekStartConfig displayWarning={displayWarning} />
                </div>
            </div>
        </>
    )
}

export function TeamBusinessModel(): JSX.Element {
    return (
        <>
            <p>Set your business model if you want tailored UI, recommendations, and insights to your use case.</p>
            <div className="deprecated-space-y-2">
                <LemonLabel id="business-model">Business model</LemonLabel>
                <BusinessModelConfig />
                <p className="text-muted text-xs">Whether this project serves B2B or B2C customers.</p>
            </div>
        </>
    )
}

export function TeamAuthorizedURLs(): JSX.Element {
    // In Storybook, allow editing by default since we don't have full app context
    const canEdit =
        inStorybook() || inStorybookTestRunner()
            ? true
            : userHasAccess(AccessControlResourceType.WebAnalytics, AccessControlLevel.Editor)

    return (
        <>
            <p>
                These are the URLs where you can see{' '}
                <b>
                    <Link to={urls.webAnalytics()}>Web Analytics</Link>
                </b>{' '}
                and{' '}
                <b>
                    <Link to={urls.experiments()}>Web Experiments</Link>
                </b>{' '}
                data from. You can also{' '}
                <b>
                    <Link to={urls.toolbarLaunch()}>launch the Toolbar</Link>
                </b>{' '}
                on these pages.
            </p>
            <p>
                <b>Wildcards are not allowed</b> (example: <code>https://*.example.com</code>). The URL needs to be
                something concrete that can be launched.
            </p>
            <AuthorizedUrlList
                type={AuthorizedUrlListType.WEB_ANALYTICS}
                allowWildCards={false}
                allowAdd={canEdit}
                allowDelete={canEdit}
            />
        </>
    )
}
