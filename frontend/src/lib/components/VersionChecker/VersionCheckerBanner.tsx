import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { teamLogic } from 'scenes/teamLogic'

import { versionCheckerLogic } from './versionCheckerLogic'

export function VersionCheckerBanner(): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const { versionWarning } = useValues(versionCheckerLogic({ teamId: currentTeamId }))
    if (!versionWarning) {
        return null
    }

    const dismissKey = `version-checker-${versionWarning.latestAvailableVersion}-${versionWarning.latestUsedVersion}`

    return (
        <LemonBanner
            type={versionWarning.level}
            dismissKey={dismissKey}
            action={{
                children: 'View the changelog',
                to: 'https://github.com/PostHog/posthog-js/blob/main/packages/browser/CHANGELOG.md',
                targetBlank: true,
            }}
            className="mb-4"
        >
            <b>Your PostHog SDK needs updating.</b> The latest version of <code>posthog-js</code> is{' '}
            <b>{versionWarning.latestAvailableVersion}</b>, but you're using <b>{versionWarning.latestUsedVersion}</b>.{' '}
            <br />
            {versionWarning.level === 'error' ? (
                <>
                    If something is not working as expected, try updating the SDK to the latest version where new
                    features and bug fixes are available.
                </>
            ) : undefined}
        </LemonBanner>
    )
}
