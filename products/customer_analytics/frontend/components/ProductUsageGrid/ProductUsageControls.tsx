import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSegmentedButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { productUsageGridLogic } from './productUsageGridLogic'

export function ProductUsageControls(): JSX.Element {
    const { controls, result } = useValues(productUsageGridLogic)
    const { setControls } = useActions(productUsageGridLogic)
    const products = result?.source.kind === 'product_usage'
    return (
        <div className="flex flex-wrap gap-2 items-center">
            <DateFilter
                dateFrom={controls.dateRange.date_from}
                dateTo={controls.dateRange.date_to}
                onChange={(date_from, date_to) => setControls({ dateRange: { date_from, date_to } })}
                size="small"
            />
            {products && (
                <LemonSegmentedButton
                    value={controls.interval}
                    onChange={(interval) => setControls({ interval })}
                    size="small"
                    options={[
                        { value: 'day', label: 'Day' },
                        { value: 'week', label: 'Week' },
                        { value: 'month', label: 'Month' },
                    ]}
                />
            )}
            <LemonSegmentedButton
                value={controls.zoom}
                onChange={(zoom) => setControls({ zoom })}
                size="small"
                options={[
                    { value: 'count', label: 'Count' },
                    { value: 'products', label: products ? 'Products' : 'Dots' },
                    ...(products ? [{ value: 'users' as const, label: 'Users' }] : []),
                ]}
            />
            {products && (
                <LemonCheckbox
                    label="Show first use"
                    checked={controls.firstUse}
                    onChange={(firstUse) => setControls({ firstUse })}
                    info="Scans account history to show first-use stars and new users."
                />
            )}
        </div>
    )
}
