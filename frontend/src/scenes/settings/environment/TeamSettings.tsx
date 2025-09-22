import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { JSSnippet, JSSnippetV2 } from 'lib/components/JSSnippet'
import { getPublicSupportSnippet } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, inStorybook, inStorybookTestRunner } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TimezoneConfig } from './TimezoneConfig'
import { WeekStartConfig } from './WeekStartConfig'

export function TeamDisplayName(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [name, setName] = useState(currentTeam?.name || '')

    const displayNoun = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <div className="deprecated-space-y-4 max-w-160">
            <LemonInput value={name} onChange={setName} disabled={currentTeamLoading} />
            <LemonButton
                type="primary"
                onClick={() => updateCurrentTeam({ name })}
                disabled={!name || !currentTeam || name === currentTeam.name}
                loading={currentTeamLoading}
            >
                Rename {displayNoun}
            </LemonButton>
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
    const { featureFlags } = useValues(featureFlagLogic)

    const displayNoun = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <>
            <p>Need to test PostHog on a live site without changing any code?</p>
            <p>
                Just drag the bookmarklet below to your bookmarks bar, open the website you want to test PostHog on and
                click it. This will enable our tracking, on the currently loaded page only. The data will show up in
                this {displayNoun}.
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
    const { featureFlags } = useValues(featureFlagLogic)

    const region = preflight?.region

    const openDialog = (): void => {
        LemonDialog.open({
            title: `Reset ${displayNoun} API key?`,
            description: 'This will invalidate the current API key and cannot be undone.',
            primaryButton: {
                children: 'Reset',
                type: 'primary',
                onClick: resetToken,
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'secondary',
            },
        })
    }

    const displayNoun = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <div className="flex items-start gap-4 flex-wrap">
            <div className="flex-1">
                <h3 id="project-api-key" className="min-w-[25rem]">
                    {capitalizeFirstLetter(displayNoun)} API key
                </h3>
                <p>
                    You can use this write-only key in any one of{' '}
                    <Link to="https://posthog.com/docs/libraries">our libraries</Link>.
                </p>
                <CodeSnippet
                    actions={
                        isTeamTokenResetAvailable ? (
                            <LemonButton icon={<IconRefresh />} noPadding onClick={openDialog} />
                        ) : undefined
                    }
                    thing={`${displayNoun} API key`}
                >
                    {currentTeam?.api_token || ''}
                </CodeSnippet>
                <p>
                    Write-only means it can only create new events. It can't read events or any of your other data
                    stored with PostHog, so it's safe to use in public apps.
                </p>
            </div>
            <div className="flex-1">
                <h3 id="project-id" className="min-w-[25rem]">
                    {capitalizeFirstLetter(displayNoun)} ID
                </h3>
                <p>
                    You can use this ID to reference your {displayNoun} in our{' '}
                    <Link to="https://posthog.com/docs/api">API</Link>.
                </p>
                <CodeSnippet thing={`${displayNoun} ID`}>{String(currentTeam?.id || '')}</CodeSnippet>
            </div>
            {region ? (
                <div className="flex-1">
                    <h3 id="project-region" className="min-w-[25rem]">
                        {capitalizeFirstLetter(displayNoun)} region
                    </h3>
                    <p>This is the region where your PostHog data is hosted.</p>
                    <CodeSnippet thing={`${displayNoun} region`}>{`${region} Cloud`}</CodeSnippet>
                </div>
            ) : null}
            <DebugInfoPanel />
        </div>
    )
}

export function TeamTimezone(): JSX.Element {
    return (
        <>
            <p>
                These settings affect how PostHog displays, buckets, and filters time-series data. You may need to
                refresh insights for new settings to apply.
            </p>
            <div className="deprecated-space-y-2">
                <LemonLabel id="timezone">Time zone</LemonLabel>
                <TimezoneConfig />
                <LemonLabel id="timezone">Week starts on</LemonLabel>
                <WeekStartConfig />
            </div>
        </>
    )
}

export function TeamAuthorizedURLs(): JSX.Element {
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
            <AuthorizedUrlList type={AuthorizedUrlListType.WEB_ANALYTICS} allowWildCards={false} />
        </>
    )
}
