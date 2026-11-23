import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import api, { ApiConfig } from 'lib/api'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { humanizeBytes } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, ExternalDataSource } from '~/types'

import {
    externalDataSourcesDisableCdcCreate,
    externalDataSourcesEnableCdcCreate,
    externalDataSourcesRepairCdcCreate,
    externalDataSourcesResumeCdcCreate,
} from 'products/warehouse_sources/frontend/generated/api'

import { sourceSettingsLogic } from './sourceSettingsLogic'

function isCdcEnabled(source: ExternalDataSource): boolean {
    // job_inputs is an EncryptedJSONField, so a stored boolean can come back as "True".
    const enabled = (source.job_inputs ?? {}).cdc_enabled
    return enabled === true || String(enabled).toLowerCase() === 'true'
}

function teamId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

function EditorAction({ source, children }: { source: ExternalDataSource; children: JSX.Element }): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.ExternalDataSource}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={source.user_access_level}
        >
            {children}
        </AccessControlAction>
    )
}

export function MySQLCDCSection({ source }: { source: ExternalDataSource }): JSX.Element {
    const enabled = isCdcEnabled(source)
    return (
        <div className="mt-6 rounded border p-4">
            <div className="flex items-center gap-2 mb-1">
                <h3 className="text-base font-semibold mb-0">Change data capture (CDC)</h3>
                {enabled && <LemonTag type="success">Enabled</LemonTag>}
                <LemonTag type="warning">Beta</LemonTag>
            </div>
            <p className="text-sm text-secondary mb-2">
                Streams inserts, updates, and <strong>deletes</strong> from the MySQL binary log. Changes are captured
                all the time and loaded into each table on its sync schedule, every 5 minutes by default.
            </p>
            <p className="text-sm text-secondary mb-3">
                Turning on CDC here doesn't change any table. Switch each table to CDC from the{' '}
                <Link to={urls.dataWarehouseSource(`managed-${source.id}`, 'schemas')}>Schemas tab</Link>.
            </p>
            <LemonDivider className="my-3" />
            {enabled ? <EnabledControls source={source} /> : <DisabledControls source={source} />}
        </div>
    )
}

function EnabledControls({ source }: { source: ExternalDataSource }): JSX.Element {
    const { loadSource, loadCdcStatus } = useActions(sourceSettingsLogic)
    const { cdcStatus: status, cdcStatusLoading, cdcStatusError } = useValues(sourceSettingsLogic)
    const [busy, setBusy] = useState(false)

    const run = async (action: () => Promise<unknown>, success: string, failure: string): Promise<void> => {
        setBusy(true)
        try {
            await action()
            lemonToast.success(success)
            loadSource()
            loadCdcStatus()
        } catch (e: any) {
            lemonToast.error(e?.message ?? failure)
        } finally {
            setBusy(false)
        }
    }

    const onRepair = (): void =>
        LemonDialog.open({
            title: 'Repair CDC',
            description:
                "PostHog starts reading the binary log again from its current end and re-syncs every CDC table from a fresh snapshot. Changes made since capture stopped can't be recovered.",
            primaryButton: {
                children: 'Repair and re-sync',
                onClick: () =>
                    void run(
                        () => externalDataSourcesRepairCdcCreate(teamId(), source.id),
                        'CDC repaired. Tables are re-syncing.',
                        "Couldn't repair CDC"
                    ),
            },
            secondaryButton: { children: 'Cancel' },
        })

    const onResume = (): void =>
        void run(() => externalDataSourcesResumeCdcCreate(teamId(), source.id), 'CDC resumed', "Couldn't resume CDC")

    const onDisable = (): void =>
        LemonDialog.open({
            title: 'Disable CDC',
            description:
                'Every table that syncs with CDC stops syncing and needs a new sync method. PostHog stops reading the binary log. You can turn CDC on again later, and it starts from the current end of the log.',
            primaryButton: {
                children: 'Disable CDC',
                status: 'danger',
                onClick: () =>
                    void run(
                        () => externalDataSourcesDisableCdcCreate(teamId(), source.id),
                        'CDC disabled',
                        "Couldn't disable CDC"
                    ),
            },
            secondaryButton: { children: 'Cancel' },
        })

    const lagBytes = status?.lag_bytes ?? null
    const lost = status?.capture_resources_present === false

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold mb-0">Binary log status</h4>
                <LemonButton size="xsmall" type="secondary" onClick={loadCdcStatus} loading={cdcStatusLoading}>
                    Refresh
                </LemonButton>
            </div>
            {cdcStatusLoading && !status ? (
                <LemonSkeleton className="h-12" />
            ) : cdcStatusError ? (
                <LemonBanner type="warning">Couldn't read live status from your database: {cdcStatusError}</LemonBanner>
            ) : status ? (
                <div className="grid grid-cols-3 gap-4 text-sm">
                    <div>
                        <div className="text-secondary text-xs">Read up to</div>
                        <code className="text-xs">{status.binlog_position ?? 'Not started'}</code>
                    </div>
                    <div>
                        <div className="text-secondary text-xs">Binary log file</div>
                        <LemonTag type={status.binlog_file_exists ? 'success' : 'danger'}>
                            {status.binlog_file_exists ? 'Kept' : 'Purged'}
                        </LemonTag>
                    </div>
                    <div>
                        <div className="text-secondary text-xs">Not yet read</div>
                        <LemonTag type="muted">{lagBytes == null ? 'Unknown' : humanizeBytes(lagBytes)}</LemonTag>
                    </div>
                </div>
            ) : null}
            {lost && (
                <LemonBanner type="error">
                    <div className="space-y-2">
                        <p className="m-0">
                            {status?.same_server === false
                                ? 'Your database now points at a different MySQL server, so the stored binary log position no longer applies.'
                                : 'MySQL deleted the binary log file PostHog was reading before PostHog read it, so changes can no longer be read.'}{' '}
                            Repairing re-syncs every CDC table from a fresh snapshot.
                        </p>
                        <EditorAction source={source}>
                            <LemonButton type="secondary" size="small" onClick={onRepair} loading={busy}>
                                Repair CDC
                            </LemonButton>
                        </EditorAction>
                    </div>
                </LemonBanner>
            )}
            {status?.schedule_paused && !lost && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <p className="m-0">
                            CDC is paused after a failure that retrying can't fix, often bad credentials. The binary log
                            position is kept, so once you fix the cause you can resume without a re-sync.
                        </p>
                        <EditorAction source={source}>
                            <LemonButton type="secondary" size="small" onClick={onResume} loading={busy}>
                                Resume CDC
                            </LemonButton>
                        </EditorAction>
                    </div>
                </LemonBanner>
            )}
            <EditorAction source={source}>
                <LemonButton type="secondary" status="danger" onClick={onDisable} loading={busy}>
                    Disable CDC
                </LemonButton>
            </EditorAction>
        </div>
    )
}

function DisabledControls({ source }: { source: ExternalDataSource }): JSX.Element {
    const { loadSource } = useActions(sourceSettingsLogic)
    const [result, setResult] = useState<{ valid: boolean; errors: string[] } | null>(null)
    const [checking, setChecking] = useState(false)
    const [enabling, setEnabling] = useState(false)

    const onCheck = async (): Promise<void> => {
        setChecking(true)
        setResult(null)
        try {
            // The source exists and its password is never sent back, so the check reads the stored credentials.
            setResult(
                await api.externalDataSources.check_cdc_prerequisites_for_source(source.id, {
                    cdc_management_mode: 'posthog',
                })
            )
        } catch (e: any) {
            lemonToast.error(e?.message ?? "Couldn't check prerequisites")
        } finally {
            setChecking(false)
        }
    }

    const onEnable = async (): Promise<void> => {
        setEnabling(true)
        try {
            await externalDataSourcesEnableCdcCreate(teamId(), source.id, {})
            lemonToast.success('CDC enabled')
            loadSource()
        } catch (e: any) {
            const errors = e?.data?.errors
            if (Array.isArray(errors) && errors.length > 0) {
                setResult({ valid: false, errors })
            } else {
                lemonToast.error(e?.message ?? "Couldn't enable CDC")
            }
        } finally {
            setEnabling(false)
        }
    }

    return (
        <div className="space-y-3">
            {result && (
                <LemonBanner type={result.valid ? 'success' : 'error'}>
                    {result.valid ? (
                        <p className="m-0">Your database is ready for CDC.</p>
                    ) : (
                        <ul className="list-disc ml-5 mb-0 text-sm">
                            {result.errors.map((error) => (
                                <li key={error}>{error}</li>
                            ))}
                        </ul>
                    )}
                </LemonBanner>
            )}
            <div className="flex gap-2">
                <LemonButton type="secondary" onClick={() => void onCheck()} loading={checking}>
                    Check database prerequisites
                </LemonButton>
                <EditorAction source={source}>
                    <LemonButton
                        type="primary"
                        onClick={() => void onEnable()}
                        loading={enabling}
                        data-attr="mysql-cdc-enable"
                    >
                        Enable CDC
                    </LemonButton>
                </EditorAction>
            </div>
        </div>
    )
}
