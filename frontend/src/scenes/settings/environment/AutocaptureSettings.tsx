import { useActions, useValues } from 'kea'
import { SupportedWebVitalsMetrics } from 'posthog-js'

import { LemonDivider, LemonSwitch } from '@posthog/lemon-ui'

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
            <p>
                You can also choose to only capture specific web vitals metrics. By default, all four core web vitals
                metrics are captured: CLS, FCP, LCP, and INP.
            </p>
            <div className="inline-grid grid-cols-2 gap-2 xs:grid xs:w-full">
                <WebVitalsAllowedMetricSwitch metric="CLS" />
                <WebVitalsAllowedMetricSwitch metric="FCP" />
                <WebVitalsAllowedMetricSwitch metric="LCP" />
                <WebVitalsAllowedMetricSwitch metric="INP" />
            </div>
        </>
    )
}
