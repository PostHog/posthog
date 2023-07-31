import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { versionCheckerLogic } from './versionCheckerLogic'

export function VersionCheckerBanner(): JSX.Element {
    const { versionWarning } = useValues(versionCheckerLogic)

    // We don't want to show a message if the diff is too small (we might be still deploying the changes out)
    if (!versionWarning || versionWarning.diff < 5) {
        return <></>
    }

    const dismissKey = `version-checker-${versionWarning.latestVersion}-${versionWarning.currentVersion}`

    return (
        <LemonBanner
            type={versionWarning.level}
            dismissKey={dismissKey}
            action={{
                children: 'Update now',
                to: 'https://posthog.com/docs/libraries/js#option-2-install-via-npm',
                targetBlank: true,
            }}
        >
            <b>Your PostHog SDK needs updating.</b> The latest version of <code>posthog-js</code> is{' '}
            <b>{versionWarning.latestVersion}</b>, but you're using <b>{versionWarning.currentVersion}</b>. <br />
            {versionWarning.level === 'error' ? (
                <>
                    If something is not working as expected, try updating the SDK to the latest version where new
                    features and bug fixes are available.
                </>
            ) : undefined}
        </LemonBanner>
    )
}
