import { LemonBanner, Link } from '@posthog/lemon-ui'

import { SurveyVersionWarning } from 'scenes/surveys/surveyVersionRequirements'

export function SdkVersionWarnings({ warnings }: { warnings: SurveyVersionWarning[] }): JSX.Element | null {
    if (warnings.length === 0) {
        return null
    }

    const warningsByFeature = warnings.reduce(
        (acc, warning) => {
            if (!acc[warning.feature]) {
                acc[warning.feature] = []
            }
            acc[warning.feature].push(warning)
            return acc
        },
        {} as Record<string, SurveyVersionWarning[]>
    )

    return (
        <LemonBanner type="warning" hideIcon>
            <div className="flex items-start gap-2">
                <div>
                    <p className="font-semibold mb-1">SDK version warning</p>
                    <ul className="text-sm list-disc pl-4 mb-2 space-y-2">
                        {Object.entries(warningsByFeature).map(([feature, featureWarnings]) => (
                            <li key={feature}>
                                <strong>{feature}</strong>
                                <ul className="list-none pl-2 mt-0.5">
                                    {featureWarnings.map((warning, idx) => (
                                        <li key={idx} className="text-secondary">
                                            Requires {warning.sdkType} v{warning.minVersion}+ (you have v
                                            {warning.currentVersion})
                                        </li>
                                    ))}
                                </ul>
                            </li>
                        ))}
                    </ul>
                    <p className="text-sm text-secondary">
                        <Link to="https://posthog.com/docs/libraries" target="_blank">
                            Update your SDK
                        </Link>{' '}
                        to ensure these features work correctly.
                    </p>
                </div>
            </div>
        </LemonBanner>
    )
}
