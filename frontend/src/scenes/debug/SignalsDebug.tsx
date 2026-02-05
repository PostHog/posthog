import { useState } from 'react'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

const SOURCE_PRODUCTS = [
    { label: 'Experiments', value: 'experiments' },
    { label: 'Web Analytics', value: 'web_analytics' },
    { label: 'Error Tracking', value: 'error_tracking' },
    { label: 'Session Replay', value: 'session_replay' },
    { label: 'Feature Flags', value: 'feature_flags' },
    { label: 'Surveys', value: 'surveys' },
    { label: 'Test', value: 'test' },
]

const SOURCE_TYPES = [
    { label: 'Significance Reached', value: 'significance_reached' },
    { label: 'Traffic Anomaly', value: 'traffic_anomaly' },
    { label: 'Error Spike', value: 'error_spike' },
    { label: 'Funnel Drop Off', value: 'funnel_drop_off' },
    { label: 'Session Anomaly', value: 'session_anomaly' },
    { label: 'Flag Evaluation Spike', value: 'flag_evaluation_spike' },
    { label: 'Survey Response Trend', value: 'survey_response_trend' },
    { label: 'Test', value: 'test' },
]

export function SignalsDebug(): JSX.Element {
    const [sourceProduct, setSourceProduct] = useState('test')
    const [sourceType, setSourceType] = useState('test')
    const [sourceId, setSourceId] = useState<string>(() => crypto.randomUUID())
    const [description, setDescription] = useState('')
    const [weight, setWeight] = useState(0.5)
    const [extraJson, setExtraJson] = useState('{}')
    const [isSubmitting, setIsSubmitting] = useState(false)

    const handleSubmit = async (): Promise<void> => {
        setIsSubmitting(true)

        let extra = {}
        try {
            extra = JSON.parse(extraJson)
        } catch {
            lemonToast.error('Invalid JSON in extra field')
            setIsSubmitting(false)
            return
        }

        try {
            await api.create(`api/environments/@current/signals/emit/`, {
                source_product: sourceProduct,
                source_type: sourceType,
                source_id: sourceId,
                description,
                weight,
                extra,
            })
            lemonToast.success('Signal emitted successfully')
            setSourceId(crypto.randomUUID())
        } catch (error) {
            lemonToast.error(`Failed to emit signal: ${error}`)
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <SceneContent>
            <h1 className="text-2xl font-bold mb-4">Signals Debug</h1>

            <div className="max-w-2xl space-y-4">
                <div className="bg-bg-3000 border rounded p-4 mb-4">
                    <p className="text-muted mb-2">
                        Use this page to test signal emission. Signals are processed by a Temporal workflow that
                        clusters them into reports. Make sure <code>sig-emit-signal-flow</code> feature flag is enabled
                        for your organization.
                    </p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <LemonLabel>Source Product</LemonLabel>
                        <LemonSelect
                            fullWidth
                            options={SOURCE_PRODUCTS}
                            value={sourceProduct}
                            onChange={(v) => v && setSourceProduct(v)}
                        />
                    </div>

                    <div>
                        <LemonLabel>Source Type</LemonLabel>
                        <LemonSelect
                            fullWidth
                            options={SOURCE_TYPES}
                            value={sourceType}
                            onChange={(v) => v && setSourceType(v)}
                        />
                    </div>
                </div>

                <div>
                    <LemonLabel>Source ID</LemonLabel>
                    <div className="flex gap-2">
                        <LemonInput
                            fullWidth
                            value={sourceId}
                            onChange={setSourceId}
                            placeholder="e.g., experiment-123"
                        />
                        <LemonButton type="secondary" onClick={() => setSourceId(crypto.randomUUID())}>
                            Random
                        </LemonButton>
                    </div>
                    <p className="text-xs text-muted mt-1">Unique identifier for the source (e.g., experiment UUID)</p>
                </div>

                <div>
                    <LemonLabel>Description</LemonLabel>
                    <LemonTextArea
                        value={description}
                        onChange={setDescription}
                        placeholder="Experiment 'Homepage CTA' reached statistical significance. Variant 'B' shows a 15% increase in conversion rate with p-value of 0.003."
                        minRows={3}
                    />
                    <p className="text-xs text-muted mt-1">This text will be embedded and used for clustering</p>
                </div>

                <div>
                    <LemonLabel>
                        Weight: {weight.toFixed(2)} {weight >= 1.0 && '(triggers immediate research)'}
                    </LemonLabel>
                    <LemonSlider min={0} max={1} step={0.05} value={weight} onChange={setWeight} />
                    <p className="text-xs text-muted mt-1">
                        0.0-1.0 importance score. Weight of 1.0 means this signal alone should trigger research.
                    </p>
                </div>

                <div>
                    <LemonLabel>Extra (JSON)</LemonLabel>
                    <LemonTextArea
                        value={extraJson}
                        onChange={setExtraJson}
                        placeholder='{"variant": "B", "p_value": 0.003}'
                        minRows={2}
                        className="font-mono text-sm"
                    />
                    <p className="text-xs text-muted mt-1">Optional product-specific metadata as JSON</p>
                </div>

                <div className="pt-4">
                    <LemonButton
                        type="primary"
                        fullWidth
                        onClick={handleSubmit}
                        loading={isSubmitting}
                        disabled={!description.trim()}
                    >
                        Emit Signal
                    </LemonButton>
                </div>

                <div className="bg-bg-3000 border rounded p-4 mt-4">
                    <h3 className="font-semibold mb-2">Quick Test Scenarios</h3>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                setSourceProduct('experiments')
                                setSourceType('significance_reached')
                                setDescription(
                                    "Experiment 'Homepage CTA' reached statistical significance. Variant 'B' shows a 15% increase in click-through rate with p-value of 0.003."
                                )
                                setWeight(0.8)
                                setExtraJson('{"variant": "B", "p_value": 0.003, "metric": "click_through_rate"}')
                            }}
                        >
                            Experiment Significance
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                setSourceProduct('web_analytics')
                                setSourceType('traffic_anomaly')
                                setDescription(
                                    "Significant traffic drop detected on '/pricing' page: -45% compared to 7-day baseline. Started 2 hours ago."
                                )
                                setWeight(0.6)
                                setExtraJson('{"page": "/pricing", "change_pct": -45, "baseline_period": "7d"}')
                            }}
                        >
                            Traffic Anomaly
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                setSourceProduct('error_tracking')
                                setSourceType('error_spike')
                                setDescription(
                                    "Error rate spike in checkout flow: 'PaymentProcessingError' increased by 300% in the last hour. Affecting 12% of checkout attempts."
                                )
                                setWeight(0.9)
                                setExtraJson(
                                    '{"error_type": "PaymentProcessingError", "increase_pct": 300, "affected_users_pct": 12}'
                                )
                            }}
                        >
                            Error Spike
                        </LemonButton>
                    </div>
                </div>
            </div>
        </SceneContent>
    )
}

export default SignalsDebug
