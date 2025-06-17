import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { ExperimentFunnelMetric, ExperimentMetric } from '~/queries/schema/schema-general'
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
                <b>Sequential</b> - Step B must happen after Step A, but any number of events can happen between A and
                B.
            </li>
            <li>
                <b>Any order</b> - Steps can be completed in any sequence.
            </li>
        </ul>
    )
}

export function ExperimentMetricFunnelOrderSelector({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentFunnelMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const handleFunnelOrderTypeChange = (funnelOrderType: StepOrderValue): void => {
        handleSetMetric({
            ...metric,
            funnel_order_type: funnelOrderType,
        })
    }

    return (
        <div className="flex items-center gap-2">
            <LemonLabel info={<StepOrderInfo />}>Step order</LemonLabel>
            <LemonSelect
                data-attr="experiment-funnel-order-selector"
                value={metric.funnel_order_type || StepOrderValue.ORDERED}
                onChange={handleFunnelOrderTypeChange}
                dropdownMatchSelectWidth={false}
                options={funnelOrderOptions}
            />
        </div>
    )
}
