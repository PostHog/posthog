import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccessControlLevel, AccessControlResourceType, ExternalDataSource } from '~/types'

import { sourceSettingsLogic } from './sourceSettingsLogic'

type ManagementMode = 'posthog' | 'self_managed'

const DEFAULT_WARN_THRESHOLD_MB = 1024
const DEFAULT_CRIT_THRESHOLD_MB = 10240

function getCdcConfig(source: ExternalDataSource): {
    enabled: boolean
    management_mode: ManagementMode
    slot_name: string
    publication_name: string
    auto_drop_slot: boolean
    lag_warning_threshold_mb: number
    lag_critical_threshold_mb: number
} {
    const ji = (source.job_inputs ?? {}) as Record<string, any>
    return {
        enabled: !!ji.cdc_enabled,
        management_mode: (ji.cdc_management_mode === 'self_managed' ? 'self_managed' : 'posthog') as ManagementMode,
        slot_name: ji.cdc_slot_name ?? '',
        publication_name: ji.cdc_publication_name ?? '',
        auto_drop_slot: ji.cdc_auto_drop_slot ?? true,
        lag_warning_threshold_mb: Number(ji.cdc_lag_warning_threshold_mb ?? DEFAULT_WARN_THRESHOLD_MB),
        lag_critical_threshold_mb: Number(ji.cdc_lag_critical_threshold_mb ?? DEFAULT_CRIT_THRESHOLD_MB),
    }
}

function confirmThen(opts: {
    title: string
    description: React.ReactNode
    primaryText: string
    primaryStatus?: 'danger' | 'alt'
    onConfirm: () => void | Promise<void>
}): void {
    LemonDialog.open({
        title: opts.title,
        description: opts.description,
        primaryButton: {
            children: opts.primaryText,
            status: opts.primaryStatus,
            onClick: () => {
                void opts.onConfirm()
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function CDCSection({ source }: { source: ExternalDataSource }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (source.source_type !== 'Postgres') {
        return null
    }
    if (source.access_method !== 'warehouse') {
        return null
    }
    if (!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_CDC]) {
        return null
    }

    const cdc = getCdcConfig(source)

    return (
        <div className="mt-6 rounded border p-4">
            <div className="flex items-center gap-2 mb-1">
                <h3 className="text-base font-semibold mb-0">Change data capture (CDC)</h3>
                <LemonTag type="completion">Alpha</LemonTag>
                {cdc.enabled && <LemonTag type="success">Enabled</LemonTag>}
            </div>
            <p className="text-sm text-secondary mb-3">
                Real-time sync via PostgreSQL logical replication. Captures inserts, updates, and{' '}
                <strong>deletes</strong> with no full table scans.
            </p>
            <LemonDivider className="my-3" />
            {cdc.enabled ? <EnabledControls source={source} /> : <DisabledControls source={source} />}
        </div>
    )
}

function EnabledControls({ source }: { source: ExternalDataSource }): JSX.Element {
    const { loadSource } = useActions(sourceSettingsLogic)
    const cdc = getCdcConfig(source)

    const [autoDrop, setAutoDrop] = useState(cdc.auto_drop_slot)
    const [warnMb, setWarnMb] = useState(cdc.lag_warning_threshold_mb)
    const [critMb, setCritMb] = useState(cdc.lag_critical_threshold_mb)
    const [busy, setBusy] = useState(false)

    const dirty =
        autoDrop !== cdc.auto_drop_slot ||
        warnMb !== cdc.lag_warning_threshold_mb ||
        critMb !== cdc.lag_critical_threshold_mb
    const thresholdsInvalid = warnMb >= critMb
    const validationError = thresholdsInvalid ? 'Warning threshold must be less than critical threshold.' : null

    const onSave = (): void => {
        if (validationError) {
            lemonToast.error(validationError)
            return
        }
        confirmThen({
            title: 'Update CDC settings',
            description:
                'Slot protection and lag thresholds will be updated for this source. New values take effect on the next CDC tick.',
            primaryText: 'Update settings',
            onConfirm: async () => {
                setBusy(true)
                try {
                    await api.externalDataSources.update_cdc_settings(source.id, {
                        cdc_auto_drop_slot: autoDrop,
                        cdc_lag_warning_threshold_mb: warnMb,
                        cdc_lag_critical_threshold_mb: critMb,
                    })
                    lemonToast.success('CDC settings updated')
                    loadSource()
                } catch (e: any) {
                    lemonToast.error(e?.message ?? "Couldn't update CDC settings")
                } finally {
                    setBusy(false)
                }
            },
        })
    }

    const onDisable = (): void => {
        confirmThen({
            title: 'Disable CDC',
            description: (
                <div className="space-y-2">
                    <p className="m-0">Disabling CDC will:</p>
                    <ul className="list-disc ml-5 m-0 text-sm">
                        <li>
                            Drop the replication slot{cdc.management_mode === 'posthog' && ' and publication'} on your
                            source database.
                        </li>
                        <li>Pause every schema currently syncing via CDC and clear its sync type.</li>
                        <li>
                            Require you to pick a new sync strategy (incremental, append, or full refresh) per schema
                            before they resume.
                        </li>
                    </ul>
                    <p className="m-0 text-sm">
                        You can re-enable CDC later — it will start from the current LSN, not from history.
                    </p>
                </div>
            ),
            primaryText: 'Disable CDC',
            primaryStatus: 'danger',
            onConfirm: async () => {
                setBusy(true)
                try {
                    await api.externalDataSources.disable_cdc(source.id)
                    lemonToast.success('CDC disabled')
                    loadSource()
                } catch (e: any) {
                    lemonToast.error(e?.message ?? "Couldn't disable CDC")
                } finally {
                    setBusy(false)
                }
            },
        })
    }

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                    <div className="text-secondary text-xs">Management mode</div>
                    <div>{cdc.management_mode === 'posthog' ? 'PostHog-managed' : 'Self-managed'}</div>
                </div>
                <div>
                    <div className="text-secondary text-xs">Replication slot</div>
                    <code className="text-xs">{cdc.slot_name}</code>
                </div>
                <div>
                    <div className="text-secondary text-xs">Publication</div>
                    <code className="text-xs">{cdc.publication_name}</code>
                </div>
            </div>

            <LemonDivider />

            <div>
                <LemonField.Pure label="Automatic slot protection" htmlFor="cdc-auto-drop-slot">
                    <LemonSwitch id="cdc-auto-drop-slot" checked={autoDrop} onChange={setAutoDrop} />
                </LemonField.Pure>
                <p className="text-xs text-secondary mt-1 mb-0">
                    When enabled, PostHog drops the replication slot if WAL lag exceeds the critical threshold —
                    preventing disk exhaustion on your database.
                </p>
            </div>

            {autoDrop && cdc.management_mode === 'posthog' && (
                <div className="grid grid-cols-2 gap-4">
                    <LemonField.Pure label="WAL lag warning (MB)">
                        <LemonInput type="number" value={warnMb} onChange={(v) => setWarnMb(Number(v) || 0)} min={1} />
                    </LemonField.Pure>
                    <LemonField.Pure label="WAL lag critical (MB)">
                        <LemonInput type="number" value={critMb} onChange={(v) => setCritMb(Number(v) || 0)} min={1} />
                    </LemonField.Pure>
                </div>
            )}

            {validationError && <LemonBanner type="error">{validationError}</LemonBanner>}

            <div className="flex justify-between items-center">
                <AccessControlAction
                    resourceType={AccessControlResourceType.ExternalDataSource}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={source.user_access_level}
                >
                    <LemonButton type="secondary" status="danger" onClick={onDisable} loading={busy}>
                        Disable CDC
                    </LemonButton>
                </AccessControlAction>
                <AccessControlAction
                    resourceType={AccessControlResourceType.ExternalDataSource}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={source.user_access_level}
                >
                    <LemonButton
                        type="primary"
                        onClick={onSave}
                        loading={busy}
                        disabledReason={!dirty ? 'No changes to save' : validationError ? validationError : undefined}
                    >
                        Save settings
                    </LemonButton>
                </AccessControlAction>
            </div>
        </div>
    )
}

function DisabledControls({ source }: { source: ExternalDataSource }): JSX.Element {
    const { loadSource } = useActions(sourceSettingsLogic)

    const [mode, setMode] = useState<ManagementMode>('posthog')
    const [publicationName, setPublicationName] = useState('')
    const [autoDrop, setAutoDrop] = useState(true)
    const [warnMb, setWarnMb] = useState(DEFAULT_WARN_THRESHOLD_MB)
    const [critMb, setCritMb] = useState(DEFAULT_CRIT_THRESHOLD_MB)
    const [prereqResult, setPrereqResult] = useState<{ valid: boolean; errors: string[] } | null>(null)
    const [checking, setChecking] = useState(false)
    const [enabling, setEnabling] = useState(false)

    const thresholdsInvalid = warnMb >= critMb

    const onCheckPrereqs = async (): Promise<void> => {
        setChecking(true)
        setPrereqResult(null)
        try {
            // Use the stored-credentials endpoint: this source already exists and its secret
            // fields (password) are stripped from API responses, so we can't resend them.
            const result = await api.externalDataSources.check_cdc_prerequisites_for_source(source.id, {
                cdc_management_mode: mode,
                cdc_publication_name: mode === 'self_managed' && publicationName ? publicationName : null,
            })
            setPrereqResult(result)
        } catch (e: any) {
            lemonToast.error(e?.message ?? "Couldn't check prerequisites")
        } finally {
            setChecking(false)
        }
    }

    const onEnable = (): void => {
        if (thresholdsInvalid) {
            lemonToast.error('Warning threshold must be less than critical threshold.')
            return
        }
        confirmThen({
            title: 'Enable CDC',
            description: (
                <div className="space-y-2">
                    <p className="m-0">Enabling CDC will:</p>
                    <ul className="list-disc ml-5 m-0 text-sm">
                        <li>
                            {mode === 'posthog'
                                ? 'Create a replication slot and publication on your source database.'
                                : 'Create a replication slot on your source database (your DBA must have already created the publication).'}
                        </li>
                        <li>Start the CDC extraction schedule.</li>
                    </ul>
                    <p className="m-0 text-sm">
                        Schemas won't switch to CDC automatically — pick CDC as the sync type on the Schemas tab once
                        this finishes.
                    </p>
                </div>
            ),
            primaryText: 'Enable CDC',
            onConfirm: async () => {
                setEnabling(true)
                try {
                    await api.externalDataSources.enable_cdc(source.id, {
                        cdc_management_mode: mode,
                        cdc_publication_name: mode === 'self_managed' && publicationName ? publicationName : null,
                        cdc_auto_drop_slot: autoDrop,
                        cdc_lag_warning_threshold_mb: warnMb,
                        cdc_lag_critical_threshold_mb: critMb,
                    })
                    lemonToast.success('CDC enabled')
                    loadSource()
                } catch (e: any) {
                    lemonToast.error(e?.message ?? "Couldn't enable CDC")
                } finally {
                    setEnabling(false)
                }
            },
        })
    }

    return (
        <div className="space-y-4">
            <LemonField.Pure label="Slot management">
                <LemonRadio
                    value={mode}
                    onChange={(v) => {
                        setMode(v)
                        setPrereqResult(null)
                    }}
                    options={[
                        {
                            value: 'posthog',
                            label: (
                                <div>
                                    <div>PostHog-managed</div>
                                    <div className="text-xs text-secondary">
                                        PostHog creates and manages the replication slot and publication. Requires a DB
                                        user with REPLICATION and table ownership.
                                    </div>
                                </div>
                            ),
                        },
                        {
                            value: 'self_managed',
                            label: (
                                <div>
                                    <div>Self-managed</div>
                                    <div className="text-xs text-secondary">
                                        You (or your DBA) create the publication once as the table owner. PostHog
                                        creates the slot and needs REPLICATION + SELECT on synced tables.
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </LemonField.Pure>

            {mode === 'self_managed' && (
                <LemonField.Pure label="Publication name">
                    <LemonInput value={publicationName} onChange={setPublicationName} placeholder="posthog_pub" />
                </LemonField.Pure>
            )}

            <div>
                <LemonField.Pure label="Automatic slot protection" htmlFor="cdc-auto-drop-slot-new">
                    <LemonSwitch id="cdc-auto-drop-slot-new" checked={autoDrop} onChange={setAutoDrop} />
                </LemonField.Pure>
                <p className="text-xs text-secondary mt-1 mb-0">
                    PostHog will drop the slot if WAL lag exceeds the critical threshold.
                </p>
            </div>

            {autoDrop && mode === 'posthog' && (
                <div className="grid grid-cols-2 gap-4">
                    <LemonField.Pure label="WAL lag warning (MB)">
                        <LemonInput type="number" value={warnMb} onChange={(v) => setWarnMb(Number(v) || 0)} min={1} />
                    </LemonField.Pure>
                    <LemonField.Pure label="WAL lag critical (MB)">
                        <LemonInput type="number" value={critMb} onChange={(v) => setCritMb(Number(v) || 0)} min={1} />
                    </LemonField.Pure>
                </div>
            )}

            {thresholdsInvalid && (
                <LemonBanner type="error">Warning threshold must be less than critical threshold.</LemonBanner>
            )}

            <div className="flex flex-col gap-2">
                <LemonButton type="secondary" onClick={onCheckPrereqs} loading={checking}>
                    Check database prerequisites
                </LemonButton>
                {prereqResult && (
                    <LemonBanner type={prereqResult.valid ? 'success' : 'error'}>
                        {prereqResult.valid ? (
                            <p className="m-0">Your database is ready for CDC.</p>
                        ) : (
                            <>
                                <p className="font-semibold mb-1">Some prerequisites are not met:</p>
                                <ul className="list-disc ml-5 mb-0 text-sm">
                                    {prereqResult.errors.map((err, i) => (
                                        <li key={i}>{err}</li>
                                    ))}
                                </ul>
                            </>
                        )}
                    </LemonBanner>
                )}
            </div>

            <div className="flex justify-end">
                <AccessControlAction
                    resourceType={AccessControlResourceType.ExternalDataSource}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={source.user_access_level}
                >
                    <LemonButton
                        type="primary"
                        onClick={onEnable}
                        loading={enabling}
                        disabledReason={
                            thresholdsInvalid
                                ? 'Fix lag threshold validation before enabling'
                                : prereqResult && !prereqResult.valid
                                  ? 'Resolve database prerequisites before enabling'
                                  : undefined
                        }
                    >
                        Enable CDC
                    </LemonButton>
                </AccessControlAction>
            </div>
        </div>
    )
}
