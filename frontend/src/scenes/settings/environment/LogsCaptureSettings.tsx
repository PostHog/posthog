import { useActions, useValues } from 'kea'

import { LemonDialog, LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    LOGS_RETENTION_DEFAULT_DAYS,
    isValidLogsRetentionDays,
    logsRetentionDaysLabel,
    retentionThrottleReason,
} from 'products/logs/frontend/components/LogsRetention/logsRetentionPeriod'
import { LogsRetentionPeriodPicker } from 'products/logs/frontend/components/LogsRetention/LogsRetentionPeriodPicker'
import { LogsRetentionSection } from 'products/logs/frontend/components/LogsRetention/LogsRetentionSection'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

export function LogsCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Logs} minAccessLevel={AccessControlLevel.Editor}>
            <LemonSwitch
                data-attr="opt-in-logs-capture-console-log-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        logs_settings: { ...currentTeam?.logs_settings, capture_console_logs: checked },
                    })
                }}
                label="Capture console logs to Logs product"
                bordered
                checked={!!currentTeam?.logs_settings?.capture_console_logs}
                loading={currentTeamLoading}
                disabledReason={restrictedReason}
            />
        </AccessControlAction>
    )
}

export function LogsJsonParseSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const isJsonParseLogs = currentTeam?.logs_settings?.json_parse_logs ?? false

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Logs}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    data-attr="logs-json-parse-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            logs_settings: { ...currentTeam?.logs_settings, json_parse_logs: checked },
                        })
                    }}
                    label="JSON parse logs"
                    bordered
                    checked={isJsonParseLogs}
                    loading={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </AccessControlAction>
        </>
    )
}

export function LogsPiiScrubSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Logs}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    data-attr="logs-pii-scrub-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            logs_settings: { ...currentTeam?.logs_settings, pii_scrub_logs: checked },
                        })
                    }}
                    label="Scrub PII in logs at ingestion"
                    bordered
                    checked={!!currentTeam?.logs_settings?.pii_scrub_logs}
                    loading={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </AccessControlAction>
            <p className="text-secondary text-sm max-w-200 mt-2">
                When enabled, we scrub common sensitive patterns from the log message body before storage: email
                addresses, Bearer-style authorization tokens, and Stripe secret key shapes. This is best-effort: values
                that do not match these patterns, or bank card numbers, may still appear. Redaction is permanent and
                one-way. Redacted values are replaced with {'{{REDACTED}}'}.
            </p>
        </>
    )
}

export function LogsRetentionSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const allowCustomRetention = useFeatureFlag(LogsFeatureFlagKeys.customRetention)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const storedRetentionDays = currentTeam?.logs_settings?.retention_days ?? LOGS_RETENTION_DEFAULT_DAYS
    // Show any stored period the backend accepts, even when the flag that offered it is now off.
    const currentRetention = isValidLogsRetentionDays(storedRetentionDays, true)
        ? storedRetentionDays
        : LOGS_RETENTION_DEFAULT_DAYS
    const retentionLastUpdated = currentTeam?.logs_settings?.retention_last_updated

    const disabledReason = currentTeamLoading
        ? 'Loading...'
        : (restrictedReason ?? retentionThrottleReason(retentionLastUpdated))

    const handleRetentionChange = (retentionDays: number): void => {
        if (retentionDays === currentRetention) {
            return
        }
        const label = logsRetentionDaysLabel(retentionDays)
        LemonDialog.open({
            title: 'Change logs retention period?',
            description:
                'Changing retention only affects logs from this point forwards. Existing logs will keep their original retention period.',
            primaryButton: {
                children: `Change retention to ${label}`,
                onClick: () =>
                    updateCurrentTeam({
                        logs_settings: {
                            ...currentTeam?.logs_settings,
                            retention_days: retentionDays,
                        },
                    }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Logs} minAccessLevel={AccessControlLevel.Editor}>
            <LogsRetentionPeriodPicker
                value={currentRetention}
                onChange={handleRetentionChange}
                allowCustom={allowCustomRetention}
                disabledReason={disabledReason}
                customCommit="apply"
            />
        </AccessControlAction>
    )
}

export function LogsRetentionSettingsBlock(): JSX.Element {
    // `LogsRetentionSection` gates itself on the retention-rules flag, so the environment
    // default below stays visible to everyone.
    return (
        <div className="flex flex-col gap-4">
            <LogsRetentionSettings />
            <LogsRetentionSection />
        </div>
    )
}
