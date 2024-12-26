import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../experimentLogic'
import { SavedFunnelsMetricForm } from './SavedFunnelsMetricForm'
import { savedMetricLogic } from './savedMetricLogic'
import { SavedTrendsMetricForm } from './SavedTrendsMetricForm'

type MetricType = 'trends' | 'funnels'

export const scene: SceneExport = {
    component: SavedMetric,
    logic: savedMetricLogic,
    paramsToProps: ({ params: { id } }) => ({
        savedMetricId: id === 'new' ? 'new' : parseInt(id),
    }),
}

export function SavedMetric(): JSX.Element {
    const { savedMetric } = useValues(savedMetricLogic)
    const { setSavedMetric, createSavedMetric } = useActions(savedMetricLogic)
    const [selectedType, setSelectedType] = useState<MetricType>('trends')

    if (!savedMetric) {
        return <div>Loading...</div>
    }

    return (
        <div>
            <div className="flex gap-4 mb-4">
                <div
                    className={`flex-1 cursor-pointer p-4 rounded border ${
                        selectedType === 'trends' ? 'border-primary bg-primary-highlight' : 'border-border'
                    }`}
                    onClick={() => {
                        setSelectedType('trends')
                        setSavedMetric({
                            query: getDefaultTrendsMetric(),
                        })
                    }}
                >
                    <div className="font-semibold flex justify-between items-center">
                        <span>Trend</span>
                        {selectedType === 'trends' && <IconCheckCircle fontSize={18} color="var(--primary)" />}
                    </div>
                    <div className="text-muted text-sm leading-relaxed">
                        Track metrics over time using events and actions. Perfect for measuring user behavior,
                        engagement rates, and other time-based metrics.
                    </div>
                </div>
                <div
                    className={`flex-1 cursor-pointer p-4 rounded border ${
                        selectedType === 'funnels' ? 'border-primary bg-primary-highlight' : 'border-border'
                    }`}
                    onClick={() => {
                        setSelectedType('funnels')
                        setSavedMetric({
                            query: getDefaultFunnelsMetric(),
                        })
                    }}
                >
                    <div className="font-semibold flex justify-between items-center">
                        <span>Funnel</span>
                        {selectedType === 'funnels' && <IconCheckCircle fontSize={18} color="var(--primary)" />}
                    </div>
                    <div className="text-muted text-sm leading-relaxed">
                        Analyze conversion rates between sequential steps. Ideal for understanding user flows, drop-off
                        points, and conversion optimization.
                    </div>
                </div>
            </div>

            {selectedType === 'trends' ? <SavedTrendsMetricForm /> : <SavedFunnelsMetricForm />}
            <LemonButton
                size="small"
                type="primary"
                onClick={() => {
                    createSavedMetric()
                }}
            >
                Save
            </LemonButton>
        </div>
    )
}
