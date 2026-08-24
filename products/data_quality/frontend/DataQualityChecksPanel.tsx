import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSwitch, LemonTag, Spinner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { CheckFormModal } from './CheckFormModal'
import { HEALTH_LABELS, HEALTH_TAG_TYPES } from './checksConstants'
import { ChecksTable } from './ChecksTable'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { dataQualityGateLogic } from './dataQualityGateLogic'
import { SuiteRunsHistory } from './SuiteRunsHistory'

interface DataQualityChecksPanelProps extends DataQualityChecksLogicProps {
    columns: DatabaseSchemaField[]
    /** Materialized views only: the gate is a project-wide setting and only bites on materialization. */
    showGateToggle?: boolean
}

export function DataQualityChecksPanel({
    columns,
    showGateToggle,
    ...logicProps
}: DataQualityChecksPanelProps): JSX.Element | null {
    const logic = dataQualityChecksLogic(logicProps)
    const {
        health,
        checks,
        checksLoading,
        enabledChecksCount,
        isSuiteRunning,
        pollTimedOut,
        runAllInFlight,
        accessDenied,
    } = useValues(logic)
    const { openCheckModal, runAll, loadChecks, loadHealth } = useActions(logic)

    if (accessDenied) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 mt-4">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <h3 className="mb-0 text-lg font-semibold">Data quality</h3>
                    {health && (
                        <LemonTag type={HEALTH_TAG_TYPES[health.health] ?? 'default'}>
                            {HEALTH_LABELS[health.health] ?? health.health}
                        </LemonTag>
                    )}
                    {health && health.checks_total > 0 && (
                        <span className="text-secondary text-sm">
                            {health.checks_failing} of {health.checks_total} failing
                        </span>
                    )}
                    {health?.health === 'unknown' && (
                        <span className="text-secondary text-sm">Run checks to see health</span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={runAll}
                        loading={runAllInFlight || isSuiteRunning}
                        disabledReason={
                            checksLoading
                                ? 'Loading checks'
                                : enabledChecksCount === 0
                                  ? 'No enabled checks to run'
                                  : undefined
                        }
                        data-attr="data-quality-run-all"
                    >
                        Run all checks
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => openCheckModal()}
                        data-attr="data-quality-new-check"
                    >
                        New check
                    </LemonButton>
                </div>
            </div>

            {isSuiteRunning && (
                <LemonBanner type="info" icon={<Spinner />}>
                    Running checks...
                </LemonBanner>
            )}
            {pollTimedOut && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Refresh',
                        onClick: () => {
                            loadChecks()
                            loadHealth()
                        },
                    }}
                >
                    Checks are still running. Check back in a few minutes.
                </LemonBanner>
            )}

            {!checksLoading && checks.length === 0 ? (
                <NoChecksYet onAddCheck={() => openCheckModal()} />
            ) : (
                <ChecksTable {...logicProps} />
            )}

            <SuiteRunsHistory {...logicProps} />

            {showGateToggle && <GateToggle />}

            <CheckFormModal {...logicProps} columns={columns} />
        </div>
    )
}

function NoChecksYet({ onAddCheck }: { onAddCheck: () => void }): JSX.Element {
    return (
        <div className="border rounded p-4 flex flex-col items-start gap-2">
            <h4 className="mb-0">No checks yet</h4>
            <p className="mb-0 text-secondary">
                Checks verify this data automatically after each sync or materialization.
            </p>
            <LemonButton type="primary" size="small" onClick={onAddCheck} data-attr="data-quality-first-check">
                Add your first check
            </LemonButton>
        </div>
    )
}

function GateToggle(): JSX.Element | null {
    const { gateConfig, gateReadable, gateSaving } = useValues(dataQualityGateLogic)
    const { setGateEnabled } = useActions(dataQualityGateLogic)

    if (!gateReadable || !gateConfig) {
        return null
    }

    return (
        <LemonSwitch
            bordered
            checked={gateConfig.gate_materialization_on_checks}
            onChange={setGateEnabled}
            loading={gateSaving}
            disabledReason={getAccessControlDisabledReason(
                AccessControlResourceType.WarehouseObjects,
                AccessControlLevel.Editor
            )}
            label="Block materialization on failing checks"
            tooltip="Applies to all materialized views in this project. When an error-severity check fails, the previous version keeps serving."
            data-attr="data-quality-gate-toggle"
        />
    )
}
