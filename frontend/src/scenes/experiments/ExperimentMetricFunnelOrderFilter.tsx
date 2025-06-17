import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { ExperimentMetric, isExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { StepOrderValue } from '~/types'

const funnelOrderOptions = [
    {
        label: 'Sequential',
        value: StepOrderValue.ORDERED,
    },
    {
        label: 'Any order',
        value: StepOrderValue.UNORDERED,
    },
]

function StepOrderInfo(): JSX.Element {
    return (
        <ul className="list-disc pl-4">
            <li>
                <b>Sequential</b> - Step B must happen after Step A, but any number events can happen between A and B.
            </li>
            <li>
                <b>Strict order</b> - Step B must happen directly after Step A without any events in between.
            </li>
            <li>
                <b>Any order</b> - Steps can be completed in any sequence.
            </li>
        </ul>
    )
}

export function ExperimentMetricFunnelOrderFilter({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element | null {
    if (!isExperimentFunnelMetric(metric)) {
        return null
    }

    const handleFunnelOrderTypeChange = (funnelOrderType: StepOrderValue): void => {
        handleSetMetric({
            ...metric,
            funnel_order_type: funnelOrderType,
        })
    }

    return (
        <div>
            <LemonLabel className="mb-1" info={<StepOrderInfo />}>
                Step order
            </LemonLabel>
            <LemonSelect
                data-attr="experiment-funnel-order-filter"
                value={metric.funnel_order_type || StepOrderValue.ORDERED}
                onChange={handleFunnelOrderTypeChange}
                dropdownMatchSelectWidth={false}
                options={funnelOrderOptions}
            />
        </div>
    )
}
