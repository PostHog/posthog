import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { SurveyFeatureWarning } from 'scenes/surveys/surveyVersionRequirements'
import { surveysSdkLogic } from 'scenes/surveys/surveysSdkLogic'

export function SdkVersionWarnings({ warnings }: { warnings: SurveyFeatureWarning[] }): JSX.Element | null {
    const { teamSdkVersions } = useValues(surveysSdkLogic)

    if (warnings.length === 0) {
        return null
    }

    const hasVersionIssues = warnings.some((w) => w.versionIssues.length > 0)

    const relevantSdks = new Set<string>()
    for (const warning of warnings) {
        for (const issue of warning.versionIssues) {
            relevantSdks.add(issue.sdkType)
        }
        for (const sdk of warning.unsupportedSdks) {
            relevantSdks.add(sdk.sdk)
        }
    }

    const sdkVersionsDisplay = Array.from(relevantSdks)
        .filter((sdk) => teamSdkVersions[sdk as keyof typeof teamSdkVersions])
        .map((sdk) => `${sdk} v${teamSdkVersions[sdk as keyof typeof teamSdkVersions]}`)
        .join(', ')

    return (
        <LemonBanner type="warning" hideIcon className="mt-2">
            <div className="flex items-start gap-2">
                <div>
                    <p className="font-semibold mb-1">SDK warnings</p>
                    {sdkVersionsDisplay && (
                        <p className="text-sm text-secondary mb-2">Your SDKs: {sdkVersionsDisplay}</p>
                    )}
                    <ul className="text-sm list-disc pl-4 mb-2 space-y-2">
                        {warnings.map((warning) => (
                            <li key={warning.feature}>
                                <strong>{warning.feature}</strong>
                                <ul className="list-none pl-2 mt-0.5 space-y-0.5">
                                    {warning.versionIssues.map((issue, idx) => (
                                        <li key={`version-${idx}`} className="text-secondary">
                                            Requires {issue.sdkType} v{issue.minVersion}+
                                        </li>
                                    ))}
                                    {warning.unsupportedSdks.map((s) => (
                                        <li key={s.sdk} className="text-secondary">
                                            {s.issue === false ? (
                                                <>Not supported on {s.sdk}</>
                                            ) : (
                                                <Link to={s.issue} target="_blank" targetBlankIcon>
                                                    Not yet supported on {s.sdk}
                                                </Link>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            </li>
                        ))}
                    </ul>
                    {hasVersionIssues && (
                        <p className="text-sm text-secondary">
                            <Link to="https://posthog.com/docs/libraries" target="_blank">
                                Update your SDK
                            </Link>{' '}
                            to ensure these features work correctly.
                        </p>
                    )}
                </div>
            </div>
        </LemonBanner>
    )
}
