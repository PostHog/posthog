import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { useState } from 'react'

import { ExperimentMetricType } from '~/queries/schema/schema-general'

interface NewMetricFormProps {
    isOpen: boolean
    onClose: () => void
    isSecondary?: boolean
}

export function NewMetricForm({ isOpen, onClose, isSecondary = false }: NewMetricFormProps): JSX.Element {
    // We'll need to hook this up to your logic later
    const metric = {
        name: '',
        metric_type: ExperimentMetricType.COUNT,
        filterTestAccounts: false,
        inverse: false,
        metric_config: {
            kind: 'ExperimentEventMetricConfig',
            event: '',
        },
    }

    const [selectedEvents, setSelectedEvents] = useState<string[]>([])

    const handleSave = () => {
        // TODO: Implement save logic
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`${isSecondary ? 'Secondary' : 'Primary'} Metric`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <LemonLabel>Name (optional)</LemonLabel>
                    <LemonInput value={metric.name} onChange={() => {}} placeholder="e.g. Revenue" />
                </div>

                <div>
                    <LemonLabel>Metric type</LemonLabel>
                    <LemonRadio
                        value={metric.metric_type}
                        onChange={(value) => {}}
                        options={[
                            {
                                label: 'Count',
                                value: ExperimentMetricType.COUNT,
                                description: 'Track the number of times an event occurs',
                            },
                            {
                                label: 'Continuous',
                                value: ExperimentMetricType.CONTINUOUS,
                                description: 'Track numeric values like revenue or time spent',
                            },
                            {
                                label: 'Funnel',
                                value: ExperimentMetricType.FUNNEL,
                                description: 'Track conversion through a series of steps',
                            },
                        ]}
                    />
                </div>

                <div>
                    <LemonLabel>Metric configuration</LemonLabel>
                    <div className="mt-2">
                        <EventSelect
                            selectedEvents={selectedEvents}
                            onChange={setSelectedEvents}
                            addElement={
                                <LemonButton type="secondary" size="small">
                                    Add event
                                </LemonButton>
                            }
                        />
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
