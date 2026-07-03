import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { useState } from 'react'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { FunnelConversionWindowTimeUnit } from '~/types'

import { ExperimentMetricConversionWindowFilter } from './ExperimentMetricConversionWindowFilter'

describe('ExperimentMetricConversionWindowFilter', () => {
    const initialMetric: ExperimentMetric = {
        kind: NodeKind.ExperimentMetric,
        metric_type: ExperimentMetricType.MEAN,
        source: {
            kind: NodeKind.EventsNode,
            event: '$pageview',
        },
        conversion_window: 14,
        conversion_window_unit: FunnelConversionWindowTimeUnit.Day,
    }

    afterEach(() => {
        cleanup()
    })

    it('keeps the conversion window input blank when cleared', () => {
        const handleSetMetric = jest.fn()

        function TestHarness(): JSX.Element {
            const [metric, setMetric] = useState(initialMetric)

            return (
                <ExperimentMetricConversionWindowFilter
                    metric={metric}
                    handleSetMetric={(newMetric) => {
                        handleSetMetric(newMetric)
                        setMetric(newMetric)
                    }}
                />
            )
        }

        const { container } = render(<TestHarness />)
        const input = container.querySelector<HTMLInputElement>(
            'input[data-attr="experiment-metric-conversion-window-input"]'
        )

        expect(input).not.toBeNull()
        expect(input).toHaveValue(14)

        fireEvent.change(input!, { target: { value: '' } })

        expect(handleSetMetric).toHaveBeenLastCalledWith(expect.objectContaining({ conversion_window: undefined }))
        expect(input).toHaveValue(null)
        expect(input).not.toHaveValue(1)
    })
})
