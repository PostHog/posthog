import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCopy } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSwitch,
    LemonTag,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

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

// Quote a (possibly schema-qualified) table identifier for SQL. `orders` -> "public"."orders";
// `analytics.events` -> "analytics"."events".
function quoteTable(name: string, defaultSchema: string): string {
    if (name.includes('.')) {
        return name
            .split('.')
            .map((part) => `"${part}"`)
            .join('.')
    }
    return `"${defaultSchema}"."${name}"`
}

// Build the self-managed CDC setup SQL the customer's DBA must run before PostHog can
// create the replication slot. Mirrors the creation wizard's dialog. Connection details
// (schema, user) come from `job_inputs` — these are non-secret so they survive the
// secret-stripping on API reads, unlike the password.
function buildSelfManagedCdcSql(source: ExternalDataSource, publicationName: string): string {
    const ji = (source.job_inputs ?? {}) as Record<string, any>
    const schema = (ji.schema as string) || 'public'
    const dbUser = (ji.user as string) || '<your_user>'
    const pubName = publicationName.trim() || 'posthog_pub'

    // No CDC tables are selected yet at enable time (schemas switch to CDC afterward on the
    // Schemas tab), so default the publication to the source's currently-synced tables — the
    // realistic CDC candidates — falling back to a placeholder when nothing is synced yet.
    const syncedTables = (source.schemas ?? []).filter((s) => s.should_sync).map((s) => s.name)
    const tableList =
        syncedTables.length > 0 ? syncedTables.map((t) => quoteTable(t, schema)).join(', ') : `"${schema}"."your_table"`

    return `-- 1. Grants for the PostHog user
--    Reading a replication slot requires REPLICATION (or rds_replication on RDS).
--    Run ONE of the lines below, depending on your environment:
ALTER USER "${dbUser}" WITH REPLICATION;             -- self-hosted / most clouds
-- GRANT rds_replication TO "${dbUser}";             -- AWS RDS
GRANT USAGE ON SCHEMA "${schema}" TO "${dbUser}";
GRANT SELECT ON ${tableList} TO "${dbUser}";

-- 2. Publication covering the tables you'll sync via CDC.
--    Run this as the table owner (or a superuser). Adjust the table list to match the
--    tables you intend to switch to CDC on the Schemas tab. PostHog creates and manages
--    the replication slot itself once you enable CDC.
CREATE PUBLICATION "${pubName}" FOR TABLE ${tableList}
  WITH (publish_via_partition_root = true);

-- Later, to add a new table to the publication:
-- ALTER PUBLICATION "${pubName}" ADD TABLE "${schema}"."new_table";`
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
    const [setupModalOpen, setSetupModalOpen] = useState(false)
    const [sqlConfirmed, setSqlConfirmed] = useState(false)
    const [modalErrors, setModalErrors] = useState<string[] | null>(null)

    const thresholdsInvalid = warnMb >= critMb

    const selfManagedSql = useMemo(() => buildSelfManagedCdcSql(source, publicationName), [source, publicationName])

    const doEnable = async (): Promise<void> => {
        setEnabling(true)
        setModalErrors(null)
        try {
            await api.externalDataSources.enable_cdc(source.id, {
                cdc_management_mode: mode,
                cdc_publication_name: mode === 'self_managed' && publicationName ? publicationName : null,
                cdc_auto_drop_slot: autoDrop,
                cdc_lag_warning_threshold_mb: warnMb,
                cdc_lag_critical_threshold_mb: critMb,
            })
            lemonToast.success('CDC enabled')
            setSetupModalOpen(false)
            loadSource()
        } catch (e: any) {
            // enable_cdc re-validates prerequisites server-side and 400s with an `errors`
            // list when the publication/grants aren't in place yet — surface those inline
            // in the modal so the user can fix their SQL and retry without losing context.
            const errs = e?.data?.errors
            if (Array.isArray(errs) && errs.length > 0) {
                setModalErrors(errs)
            } else {
                lemonToast.error(e?.message ?? "Couldn't enable CDC")
            }
        } finally {
            setEnabling(false)
        }
    }

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

        // Self-managed: the publication must exist before PostHog can create the slot. Walk the
        // user through the setup SQL first, then enable (which verifies it server-side).
        if (mode === 'self_managed') {
            if (!publicationName.trim()) {
                lemonToast.error('Enter a publication name first.')
                return
            }
            setModalErrors(null)
            setSqlConfirmed(false)
            setSetupModalOpen(true)
            return
        }

        // PostHog-managed: PostHog creates the slot + publication itself, no SQL to run.
        confirmThen({
            title: 'Enable CDC',
            description: (
                <div className="space-y-2">
                    <p className="m-0">Enabling CDC will:</p>
                    <ul className="list-disc ml-5 m-0 text-sm">
                        <li>Create a replication slot and publication on your source database.</li>
                        <li>Start the CDC extraction schedule.</li>
                    </ul>
                    <p className="m-0 text-sm">
                        Schemas won't switch to CDC automatically — pick CDC as the sync type on the Schemas tab once
                        this finishes.
                    </p>
                </div>
            ),
            primaryText: 'Enable CDC',
            onConfirm: doEnable,
        })
    }

    return (
        <>
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
                                            PostHog creates and manages the replication slot and publication. Requires a
                                            DB user with REPLICATION and table ownership.
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
                            <LemonInput
                                type="number"
                                value={warnMb}
                                onChange={(v) => setWarnMb(Number(v) || 0)}
                                min={1}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="WAL lag critical (MB)">
                            <LemonInput
                                type="number"
                                value={critMb}
                                onChange={(v) => setCritMb(Number(v) || 0)}
                                min={1}
                            />
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
                                    : // For self-managed the modal walks the user through the publication SQL and
                                      // verifies on enable, so a failed standalone check (no publication yet) must
                                      // not block opening it.
                                      mode === 'posthog' && prereqResult && !prereqResult.valid
                                      ? 'Resolve database prerequisites before enabling'
                                      : undefined
                            }
                        >
                            {mode === 'self_managed' ? 'Set up & enable CDC' : 'Enable CDC'}
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            <LemonModal
                isOpen={setupModalOpen}
                onClose={() => setSetupModalOpen(false)}
                title="Create your publication"
                description="Self-managed CDC needs the publication to exist before PostHog connects — PostHog creates and manages the replication slot itself. Run the SQL below as the table owner, then enable CDC."
                width={720}
                footer={
                    <>
                        <LemonButton
                            type="tertiary"
                            onClick={() => setSetupModalOpen(false)}
                            disabledReason={enabling ? 'Enabling...' : undefined}
                        >
                            Back
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={enabling}
                            disabledReason={!sqlConfirmed ? 'Confirm you have executed the SQL' : undefined}
                            onClick={() => void doEnable()}
                        >
                            Verify & enable CDC
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-3">
                    <div className="flex justify-end">
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() => void copyToClipboard(selfManagedSql, 'Setup SQL')}
                        >
                            Copy SQL
                        </LemonButton>
                    </div>
                    <pre className="text-xs bg-surface-primary p-3 rounded overflow-x-auto whitespace-pre-wrap border border-border">
                        {selfManagedSql}
                    </pre>

                    <LemonCheckbox
                        checked={sqlConfirmed}
                        onChange={setSqlConfirmed}
                        label="I have executed the SQL above on my PostgreSQL database"
                    />

                    {modalErrors && modalErrors.length > 0 && (
                        <LemonBanner type="error">
                            <p className="font-semibold mb-1">
                                Verification failed — please fix the following and retry:
                            </p>
                            <ul className="list-disc ml-5 mb-0 text-sm">
                                {modalErrors.map((err, i) => (
                                    <li key={i}>{err}</li>
                                ))}
                            </ul>
                        </LemonBanner>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
