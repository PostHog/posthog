import { useState } from 'react'

import { IconCheck, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DetectorConfig } from '~/queries/schema/schema-general'

import { AlertType, BackfillResult } from '../types'

interface BackfillPreviewProps {
    insightId: number
    seriesIndex: number
    detectorConfig: DetectorConfig | null | undefined
    disabled?: boolean
    alertId?: AlertType['id']
    onBackfillComplete?: () => void
}

export function BackfillPreview({
    insightId,
    seriesIndex,
    detectorConfig,
    disabled = false,
    alertId,
    onBackfillComplete,
}: BackfillPreviewProps): JSX.Element {
    const [nObservations, setNObservations] = useState(100)
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState<BackfillResult | null>(null)
    const [error, setError] = useState<string | null>(null)

    const runBackfill = async (saveResults: boolean): Promise<void> => {
        if (!detectorConfig) {
            setError('No detector configured')
            return
        }

        setLoading(true)
        setError(null)
        setResult(null)

        try {
            const response = await api.alerts.backfill({
                detector_config: detectorConfig,
                n_observations: nObservations,
                insight_id: insightId,
                series_index: seriesIndex,
                alert_id: saveResults && alertId ? alertId : undefined,
            })
            setResult(response)

            if (saveResults && response.saved_check_id && onBackfillComplete) {
                onBackfillComplete()
            }
        } catch (e: any) {
            setError(e.message || 'Backfill failed')
        } finally {
            setLoading(false)
        }
    }

    const canSave = !!alertId

    return (
        <div className="border rounded p-4 mt-4 bg-surface-primary-alt">
            <div className="flex justify-between items-center mb-3">
                <h4 className="m-0 text-sm font-semibold">Backfill</h4>
            </div>

            <div className="flex gap-3 items-center mb-3">
                <div className="flex items-center gap-2">
                    <span className="text-sm">Analyze last</span>
                    <LemonInput
                        type="number"
                        className="w-20"
                        value={nObservations}
                        onChange={(value) => setNObservations(value ?? 100)}
                        min={10}
                        max={200}
                    />
                    <span className="text-sm">observations</span>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={() => runBackfill(false)}
                    loading={loading}
                    disabled={disabled || !detectorConfig}
                    tooltip={
                        !detectorConfig ? 'Configure a detector first' : 'Preview anomaly detection without saving'
                    }
                >
                    Preview
                </LemonButton>
                {canSave && (
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconCheck />}
                        onClick={() => runBackfill(true)}
                        loading={loading}
                        disabled={disabled || !detectorConfig}
                        tooltip="Run detection and save results as alert checks"
                    >
                        Run & save
                    </LemonButton>
                )}
            </div>

            {error && <div className="text-danger text-sm mb-2">{error}</div>}

            {result && (
                <div className="space-y-2">
                    {result.saved_check_id && (
                        <div className="text-success text-sm font-medium mb-2">
                            ✓ Results saved
                            {result.anomaly_count > 0 && (
                                <span>
                                    {' '}
                                    - enable "Show alert points" in chart settings to see anomalies on the chart
                                </span>
                            )}
                        </div>
                    )}
                    <div className="flex gap-4 text-sm">
                        <div>
                            <span className="text-muted-alt">Total points:</span>{' '}
                            <span className="font-medium">{result.total_points}</span>
                        </div>
                        <div>
                            <span className="text-muted-alt">Anomalies:</span>{' '}
                            <span
                                className={`font-medium ${result.anomaly_count > 0 ? 'text-warning' : 'text-success'}`}
                            >
                                {result.anomaly_count}
                            </span>
                        </div>
                        <div>
                            <span className="text-muted-alt">Rate:</span>{' '}
                            <span className="font-medium">
                                {result.total_points > 0
                                    ? ((result.anomaly_count / result.total_points) * 100).toFixed(1)
                                    : 0}
                                %
                            </span>
                        </div>
                    </div>

                    {result.triggered_indices.length > 0 && (
                        <div className="text-sm">
                            <span className="text-muted-alt">Triggered at indices:</span>{' '}
                            <span className="font-mono text-xs">
                                {result.triggered_indices.slice(0, 10).join(', ')}
                                {result.triggered_indices.length > 10 &&
                                    ` ... +${result.triggered_indices.length - 10} more`}
                            </span>
                        </div>
                    )}

                    {result.anomaly_count === 0 && (
                        <div className="text-success text-sm">No anomalies detected in the sample period</div>
                    )}
                </div>
            )}
        </div>
    )
}
