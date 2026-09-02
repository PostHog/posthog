import { useActions, useValues } from 'kea'
import { SupportedWebVitalsMetrics } from 'posthog-js'

import { LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

function WebVitalsAllowedMetricSwitch({ metric }: { metric: SupportedWebVitalsMetrics }): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

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
                      ? restrictedReason
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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

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
                    disabledReason={restrictedReason}
                    label="Enable autocapture for web"
                    bordered
                />
            </div>
            <AutocapturePrivacyGuidance />
        </>
    )
}

function AutocapturePrivacyGuidance(): JSX.Element {
    return (
        <div className="text-secondary text-sm max-w-200 mt-4 deprecated-space-y-2">
            <p className="m-0">
                Autocapture records clicks, inputs, and page URLs. Text you type into forms is not captured, but element
                labels, placeholders, and URLs can still hold personal data. Keep PII or PHI out at two points:
            </p>
            <ul className="list-disc pl-4 deprecated-space-y-1">
                <li>
                    In the browser, before events are sent. Add the <code>ph-no-capture</code> class to elements you
                    want to skip, or edit events with <code>before_send</code>. See{' '}
                    <Link to="https://posthog.com/docs/privacy/data-collection#hide-sensitive-information-with-autocapture">
                        hiding sensitive elements
                    </Link>{' '}
                    and{' '}
                    <Link to="https://posthog.com/docs/privacy/data-collection#overriding-captured-events">
                        editing events with before_send
                    </Link>
                    .
                </li>
                <li>
                    At ingestion, as a safety net for every SDK. The{' '}
                    <Link to={urls.hogFunctionNew('template-hash-properties')}>Hash properties transformation</Link>{' '}
                    hashes chosen properties with SHA-256 before events are stored. It hashes string values only, so
                    numbers and other non-string values pass through unchanged. Send those as strings if you need them
                    hashed.
                </li>
            </ul>
            <p className="m-0">
                For the full picture, read the{' '}
                <Link to="https://posthog.com/docs/privacy/data-collection">privacy controls guide</Link>.
            </p>
        </div>
    )
}

export function WebVitalsAutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

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
                disabledReason={restrictedReason}
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
