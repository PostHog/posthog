import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { externalTableSyncLogic } from './externalTableSyncLogic'

export function ExternalTableSync({ tableId }: { tableId: string }): JSX.Element {
    const logic = externalTableSyncLogic({ tableId })
    const { settings, settingsLoading, enabled, intervalMinutes, loadError } = useValues(logic)
    const { setEnabled, setIntervalMinutes, saveSettings, loadExternalTableSync } = useActions(logic)

    return (
        <div className="flex flex-col gap-4">
            <LemonDivider />
            <h3 className="mb-0">Warehouse sync</h3>
            <p className="mb-0 max-w-prose">
                Sync Delta tables into your managed warehouse to query them through Trino. Your source files stay in
                your bucket. Each changed version copies the full table and may incur storage and transfer costs.
            </p>
            {settingsLoading && !settings ? (
                <Spinner />
            ) : loadError ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadExternalTableSync }}>
                    Couldn't load warehouse sync settings. Try again.
                </LemonBanner>
            ) : settings ? (
                <>
                    {settings.unavailable_reason && (
                        <LemonBanner type="info">{settings.unavailable_reason}</LemonBanner>
                    )}
                    <LemonSwitch
                        label="Sync to warehouse"
                        checked={enabled}
                        onChange={setEnabled}
                        disabledReason={
                            settingsLoading
                                ? 'Saving or loading sync settings'
                                : !settings.available && !settings.enabled
                                  ? settings.unavailable_reason
                                  : undefined
                        }
                        data-attr="external-table-warehouse-sync-toggle"
                    />
                    {enabled && (
                        <div className="flex flex-col gap-2 items-start">
                            <LemonLabel htmlFor={`warehouse-sync-interval-${tableId}`}>Refresh interval</LemonLabel>
                            <LemonSelect
                                id={`warehouse-sync-interval-${tableId}`}
                                value={intervalMinutes}
                                onChange={setIntervalMinutes}
                                options={[
                                    { value: 5, label: 'Every 5 minutes' },
                                    { value: 15, label: 'Every 15 minutes' },
                                    { value: 60, label: 'Every hour' },
                                    { value: 360, label: 'Every 6 hours' },
                                    { value: 1440, label: 'Every day' },
                                    { value: 10080, label: 'Every week' },
                                ]}
                                disabledReason={settingsLoading ? 'Saving or loading sync settings' : undefined}
                                data-attr="external-table-warehouse-sync-interval"
                            />
                        </div>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <span>Status</span>
                        <LemonTag
                            type={
                                settings.status === 'ready'
                                    ? 'success'
                                    : settings.status === 'error'
                                      ? 'danger'
                                      : 'default'
                            }
                        >
                            {
                                {
                                    disabled: 'Off',
                                    preparing: 'Preparing first copy',
                                    ready: 'Ready',
                                    error: 'Refresh failed',
                                }[settings.status]
                            }
                        </LemonTag>
                        {settings.last_synced_at && (
                            <span className="text-secondary">{`Last refreshed ${dayjs(settings.last_synced_at).format('MMM D, YYYY HH:mm')}`}</span>
                        )}
                    </div>
                    {settings.error && <LemonBanner type="error">{settings.error}</LemonBanner>}
                    <p className="mb-0 text-secondary">Turning sync off keeps the last published warehouse copy.</p>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="primary"
                            onClick={saveSettings}
                            loading={settingsLoading}
                            disabledReason={enabled && !settings.available ? settings.unavailable_reason : undefined}
                            data-attr="external-table-warehouse-sync-save"
                        >
                            Save sync settings
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={loadExternalTableSync}
                            disabledReason={settingsLoading ? 'Saving or loading sync settings' : undefined}
                            data-attr="external-table-warehouse-sync-refresh-status"
                        >
                            Refresh status
                        </LemonButton>
                    </div>
                </>
            ) : null}
        </div>
    )
}
