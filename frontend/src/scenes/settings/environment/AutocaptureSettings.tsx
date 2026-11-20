import { useActions, useValues } from 'kea'
import { SupportedWebVitalsMetrics } from 'posthog-js'

import { LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { Separator, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { QuillSettingSwitch } from '../components/QuillSettingSwitch'

function WebVitalsAllowedMetricSwitch({ metric }: { metric: SupportedWebVitalsMetrics }): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const label = `Capture ${metric}`
    const isAllowed = currentTeam?.autocapture_web_vitals_allowed_metrics
        ? currentTeam?.autocapture_web_vitals_allowed_metrics?.includes(metric)
        : true
    const disabledReason = userLoading
        ? 'Loading user'
        : currentTeam?.autocapture_web_vitals_opt_in
          ? restrictedReason
          : 'Enable web vitals autocapture to set allowed metrics'
    const handleChange = (checked: boolean): void => {
        if (!currentTeam) {
            // shouldn't ever get here without a team, but we certainly can't edit it if it's not there
            return
        }

        const without = (currentTeam?.autocapture_web_vitals_allowed_metrics || ['FCP', 'CLS', 'INP', 'LCP'])?.filter(
            (allowedMetric) => allowedMetric !== metric
        )
        if (checked) {
            updateCurrentTeam({
                autocapture_web_vitals_allowed_metrics: [...without, metric],
            })
        } else {
            updateCurrentTeam({
                autocapture_web_vitals_allowed_metrics: [...without],
            })
        }
    }

    return todayRailNav ? (
        <QuillSettingSwitch
            label={label}
            checked={isAllowed}
            onCheckedChange={handleChange}
            disabledReason={disabledReason}
        />
    ) : (
        <LemonSwitch
            label={label}
            bordered
            checked={isAllowed}
            disabledReason={disabledReason}
            onChange={handleChange}
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({
            autocapture_opt_out: !checked,
        })
        reportAutocaptureToggled(!checked)
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                id="posthog-autocapture-switch"
                label="Enable autocapture for web"
                checked={!currentTeam?.autocapture_opt_out}
                onCheckedChange={handleChange}
                disabled={userLoading}
                disabledReason={restrictedReason}
            />
        )
    }

    return (
        <>
            <div className="deprecated-space-y-2">
                <LemonSwitch
                    id="posthog-autocapture-switch"
                    onChange={handleChange}
                    checked={!currentTeam?.autocapture_opt_out}
                    disabled={userLoading}
                    disabledReason={restrictedReason}
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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateCurrentTeam({
            autocapture_web_vitals_opt_in: checked,
        })
    }
    const metricSwitches = (
        <>
            <WebVitalsAllowedMetricSwitch metric="CLS" />
            <WebVitalsAllowedMetricSwitch metric="FCP" />
            <WebVitalsAllowedMetricSwitch metric="LCP" />
            <WebVitalsAllowedMetricSwitch metric="INP" />
        </>
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <QuillSettingSwitch
                    id="posthog-autocapture-web-vitals-switch"
                    label="Enable web vitals autocapture"
                    checked={!!currentTeam?.autocapture_web_vitals_opt_in}
                    onCheckedChange={handleChange}
                    disabled={userLoading}
                    disabledReason={restrictedReason}
                />
                <Separator className="my-2" />
                <Text size="xs" render={<p className="m-0" />}>
                    You can also choose to only capture specific web vitals metrics. By default, all four core web
                    vitals metrics are captured: CLS, FCP, LCP, and INP.
                </Text>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 w-fit">{metricSwitches}</div>
            </div>
        )
    }

    return (
        <>
            <LemonSwitch
                id="posthog-autocapture-web-vitals-switch"
                onChange={handleChange}
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
            <div className="inline-grid grid-cols-2 gap-2 xs:grid xs:w-full">{metricSwitches}</div>
        </>
    )
}
