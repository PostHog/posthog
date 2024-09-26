import { urls } from '@posthog/apps-common'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { JSBookmarklet } from 'lib/components/JSBookmarklet'
import { JSSnippet } from 'lib/components/JSSnippet'
import { getPublicSupportSnippet } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

import { TimezoneConfig } from './TimezoneConfig'
import { WeekStartConfig } from './WeekStartConfig'

export function TeamDisplayName(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [name, setName] = useState(currentTeam?.name || '')

    const displayNoun = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    if (currentTeam?.is_demo) {
        return (
            <p>
                <i>The demo {displayNoun} cannot be renamed.</i>
            </p>
        )
    }

    return (
        <div className="space-y-4 max-w-160">
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
                <div className="space-y-4">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton repeat={3} />
                </div>
            ) : (
                <JSSnippet />
            )}
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

export function TeamVariables(): JSX.Element {
    const { currentTeam, isTeamTokenResetAvailable } = useValues(teamLogic)
    const { resetToken } = useActions(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
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
            {region && currentOrganization && currentTeam ? (
                <div className="flex-1 max-w-full">
                    <h3 id="debug-info" className="min-w-[25rem]">
                        Debug information
                    </h3>
                    <p>Include this snippet when creating an issue (feature request or bug report) on GitHub.</p>
                    <CodeSnippet compact thing="debug info">
                        {getPublicSupportSnippet(region, currentOrganization, currentTeam, false)}
                    </CodeSnippet>
                </div>
            ) : null}
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
            <div className="space-y-2">
                <LemonLabel id="timezone">Time zone</LemonLabel>
                <TimezoneConfig />
                <LemonLabel id="timezone">Week starts on</LemonLabel>
                <WeekStartConfig />
            </div>
        </>
    )
}

export function TeamToolbarURLs(): JSX.Element {
    return (
        <>
            <p>
                These are the URLs where the{' '}
                <b>
                    <Link to={urls.toolbarLaunch()}>Toolbar</Link> will automatically launch
                </b>{' '}
                (if you're logged in).
            </p>
            <p>
                <b>Domains and wildcard subdomains are allowed</b> (example: <code>https://*.example.com</code>).
                However, wildcarded top-level domains cannot be used (for security reasons).
            </p>
            <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} />
        </>
    )
}
