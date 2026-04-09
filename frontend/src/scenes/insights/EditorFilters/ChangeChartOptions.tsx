import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { getChangeChartVizOptions } from 'scenes/insights/views/ChangeChart/changeChartData'

import { ChartDisplayType } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function ChangeChartOptions(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { vizSpecificOptions } = useValues(insightVizDataLogic(insightProps))
    const { updateVizSpecificOptions } = useActions(insightVizDataLogic(insightProps))

    const options = getChangeChartVizOptions(vizSpecificOptions)

    return (
        <div className="px-2 pb-2 flex flex-col gap-2">
            <LemonSegmentedButton
                value={options.displayMode}
                onChange={(value) =>
                    updateVizSpecificOptions({
                        [ChartDisplayType.ChangeChart]: {
                            ...options,
                            displayMode: value as 'relative' | 'absolute',
                        },
                    })
                }
                options={[
                    { value: 'relative', label: 'Relative' },
                    { value: 'absolute', label: 'Absolute' },
                ]}
                size="small"
                fullWidth
            />
            <LemonSelect
                value={options.orderBy}
                onChange={(value) =>
                    updateVizSpecificOptions({
                        [ChartDisplayType.ChangeChart]: {
                            ...options,
                            orderBy: value as 'change' | 'name' | 'currentValue' | 'previousValue',
                        },
                    })
                }
                options={[
                    { value: 'change', label: 'Order by change' },
                    { value: 'name', label: 'Order by name' },
                    { value: 'currentValue', label: 'Order by present value' },
                    { value: 'previousValue', label: 'Order by past value' },
                ]}
                size="small"
                fullWidth
            />
            <LemonSegmentedButton
                value={options.orderDirection}
                onChange={(value) =>
                    updateVizSpecificOptions({
                        [ChartDisplayType.ChangeChart]: {
                            ...options,
                            orderDirection: value as 'asc' | 'desc',
                        },
                    })
                }
                options={[
                    { value: 'desc', label: 'Desc' },
                    { value: 'asc', label: 'Asc' },
                ]}
                size="small"
                fullWidth
            />
            <LemonCheckbox
                checked={options.showCurrentValue}
                onChange={() =>
                    updateVizSpecificOptions({
                        [ChartDisplayType.ChangeChart]: {
                            ...options,
                            showCurrentValue: !options.showCurrentValue,
                        },
                    })
                }
                label={<span className="font-normal">Show current value</span>}
                size="small"
            />
        </div>
    )
}
