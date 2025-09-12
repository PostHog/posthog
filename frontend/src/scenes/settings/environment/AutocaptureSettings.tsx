import { useActions, useValues } from 'kea'
import { SupportedWebVitalsMetrics } from 'posthog-js'

import { LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

function WebVitalsAllowedMetricSwitch({ metric }: { metric: SupportedWebVitalsMetrics }): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <LemonSwitch
            label={`Capture ${metric}`}
            bordered
            checked={
                currentTeam?.autocapture_web_vitals_allowed_metrics
                    ? currentTeam?.autocapture_web_vitals_allowed_metrics?.includes(metric)
                    : true
            }
            disabledReason={
                userLoading
                    ? 'Loading user'
                    : currentTeam?.autocapture_web_vitals_opt_in
                      ? null
                      : 'Enable web vitals autocapture to set allowed metrics'
            }
            onChange={(checked) => {
                if (!currentTeam) {
                    // shouldn't ever get here without a team, but we certainly can't edit it if it's not there
                    return
                }

                const without = (
                    currentTeam?.autocapture_web_vitals_allowed_metrics || ['FCP', 'CLS', 'INP', 'LCP']
                )?.filter((allowedMetric) => allowedMetric !== metric)
                if (checked) {
                    updateCurrentTeam({
                        autocapture_web_vitals_allowed_metrics: [...without, metric],
                    })
                } else {
                    updateCurrentTeam({
                        autocapture_web_vitals_allowed_metrics: [...without],
                    })
                }
            }}
        />
    )
}

export function AutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportAutocaptureToggled } = useActions(eventUsageLogic)

    return (
        <>
            <p>
                Automagically capture frontend events, such as any <code>click</code>, <code>change of input</code>, or
                submission associated with a <code>button</code>, <code>form</code>, <code>input</code>,{' '}
                <code>select</code>, or <code>textarea</code>, when using our web JavaScript SDK.
            </p>

            <p>
                Autocapture is also available for{' '}
                <Link to="https://posthog.com/docs/libraries/react-native#autocapture" target="_blank">
                    React Native
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/docs/libraries/ios#autocapture" target="_blank">
                    iOS
                </Link>
                , where they can be configured directly in code.
            </p>

            <div className="deprecated-space-y-2">
                <LemonSwitch
                    id="posthog-autocapture-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            autocapture_opt_out: !checked,
                        })
                        reportAutocaptureToggled(!checked)
                    }}
                    checked={!currentTeam?.autocapture_opt_out}
                    disabled={userLoading}
                    label="Enable autocapture for web"
                    bordered
                />
            </div>
        </>
    )
}

export function WebVitalsAutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <>
            <p>
                Since posthog-js version 1.141.2 you can enable{' '}
                <Link to="https://github.com/GoogleChrome/web-vitals" target="_blank">
                    Google Chrome's web vitals
                </Link>{' '}
                collection. Web vitals events can be used in insights, and when web vitals capture is enabled it is used
                to enhance other parts of PostHog like web analytics and session replay.
            </p>
            <LemonSwitch
                id="posthog-autocapture-web-vitals-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        autocapture_web_vitals_opt_in: checked,
                    })
                }}
                checked={!!currentTeam?.autocapture_web_vitals_opt_in}
                disabled={userLoading}
                label="Enable web vitals autocapture"
                bordered
            />
            <LemonDivider />
            <p>You can choose which metrics to capture. By default, we capture all metrics.</p>
            <div className="inline-grid grid-cols-2 gap-2 xs:grid xs:w-full">
                <WebVitalsAllowedMetricSwitch metric="CLS" />
                <WebVitalsAllowedMetricSwitch metric="FCP" />
                <WebVitalsAllowedMetricSwitch metric="LCP" />
                <WebVitalsAllowedMetricSwitch metric="INP" />
            </div>
        </>
    )
}
