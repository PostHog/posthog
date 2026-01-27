import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

const MIN_POSTHOG_JS_VERSION = '1.329.0'

export function LogsCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <div>
            <LemonBanner
                type="info"
                className="mb-4"
                action={{
                    children: 'View SDK docs',
                    to: 'https://posthog.com/docs/libraries/js',
                    targetBlank: true,
                }}
            >
                This feature requires <code>posthog-js</code> version {MIN_POSTHOG_JS_VERSION} or higher.
            </LemonBanner>
            <h3>Browser console logs capture</h3>
            <p>
                Automatically capture browser session logs from your application and send them to the Logs product for
                analysis and debugging.
            </p>
            <p>
                This is separate from session replay console log capture and specifically sends logs to PostHog's
                dedicated Logs product.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.Logs}
                minAccessLevel={AccessControlLevel.Editor}
            >
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
                />
            </AccessControlAction>
        </div>
    )
}

export function LogsJsonParseSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    const isJsonParseLogs = currentTeam?.logs_settings?.json_parse_logs ?? true

    return (
        <>
            <p>
                This will parse any log lines which are valid JSON and add those JSON fields as log attributes that can
                be used in filters
            </p>
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
                />
            </AccessControlAction>
        </>
    )
}

export function LogsRetentionSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    const savedRetentionDays = currentTeam?.logs_settings?.retention_days ?? 15
    const retentionLastUpdated = currentTeam?.logs_settings?.retention_last_updated

    const [retentionDays, setRetentionDays] = useState(savedRetentionDays)
    const [showConfirmModal, setShowConfirmModal] = useState(false)

    const hasChanges = retentionDays !== savedRetentionDays
    const isReducingRetention = retentionDays < savedRetentionDays

    const getUpdateStatus = (): { canUpdate: boolean; hoursRemaining: number } => {
        if (!retentionLastUpdated) {
            return { canUpdate: true, hoursRemaining: 0 }
        }
        const lastUpdated = dayjs(retentionLastUpdated)
        const hoursSinceUpdate = dayjs().diff(lastUpdated, 'hours')
        const hoursRemaining = Math.max(0, 24 - hoursSinceUpdate)
        return { canUpdate: hoursSinceUpdate >= 24, hoursRemaining }
    }

    const { canUpdate, hoursRemaining } = getUpdateStatus()

    const performSave = (): void => {
        updateCurrentTeam({
            logs_settings: {
                ...currentTeam?.logs_settings,
                retention_days: retentionDays,
            },
        })
        setShowConfirmModal(false)
    }

    const handleSave = (): void => {
        if (isReducingRetention) {
            setShowConfirmModal(true)
        } else {
            performSave()
        }
    }

    const getDisabledReason = (): string | undefined => {
        if (!hasChanges) {
            return 'No change to save'
        }
        if (!canUpdate) {
            return `You can update retention again in ${hoursRemaining} hour${hoursRemaining !== 1 ? 's' : ''}`
        }
        return undefined
    }

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Logs} minAccessLevel={AccessControlLevel.Editor}>
            <div className="space-y-2">
                <label className="font-semibold">Retention (days)</label>
                <p className="text-muted">
                    How long to retain logs before they are automatically deleted. You can only change this setting at
                    most once per 24 hours
                </p>
                <LemonInput
                    data-attr="logs-retention-input"
                    type="number"
                    value={retentionDays}
                    onChange={(value) => {
                        setRetentionDays(value || NaN)
                    }}
                    min={2}
                    max={90}
                    suffix={<>days</>}
                />
                {retentionDays < 15 && (
                    <LemonBanner type="info">
                        15 days is free. There's no discount for less than 15 days retention.
                    </LemonBanner>
                )}
                {hasChanges && canUpdate && (
                    <LemonBanner type="warning">You can only update retention settings once per 24 hours.</LemonBanner>
                )}
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    loading={currentTeamLoading}
                    disabledReason={getDisabledReason()}
                    data-attr="logs-retention-save"
                >
                    Save retention settings
                </LemonButton>

                <LemonModal
                    isOpen={showConfirmModal}
                    onClose={() => setShowConfirmModal(false)}
                    title="Confirm retention reduction"
                    footer={
                        <>
                            <LemonButton type="secondary" onClick={() => setShowConfirmModal(false)}>
                                Cancel
                            </LemonButton>
                            <LemonButton type="primary" status="danger" onClick={performSave}>
                                Reduce retention
                            </LemonButton>
                        </>
                    }
                >
                    <p>
                        Are you sure you want to reduce retention? Up to {savedRetentionDays - retentionDays} days of
                        logs will be <strong>permanently deleted</strong>.
                    </p>
                </LemonModal>
            </div>
        </AccessControlAction>
    )
}
