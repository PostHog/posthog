import { LemonSegmentedButton, LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useState } from 'react'

import { Query } from '~/queries/Query/Query'

import { errorTrackingLogic } from '../errorTrackingLogic'
import { errorTrackingGroupBreakdownQuery } from '../queries'

const gridColumnsMap = {
    small: 'grid-cols-1',
    medium: 'grid-cols-2',
    large: 'grid-cols-3',
}

type BreakdownGroup = { title: string; options: LemonSegmentedButtonOption<string>[] }

export const BreakdownsTab = (): JSX.Element => {
    const breakdownGroups: BreakdownGroup[] = [
        {
            title: 'Device',
            options: [
                { value: '$browser', label: 'Browser' },
                { value: '$device_type', label: 'Device type' },
                { value: '$os', label: 'Operating system' },
            ],
        },
        {
            title: 'User',
            options: [
                { value: '$user_id', label: 'User ID' },
                { value: '$ip', label: 'IP address' },
            ],
        },
        { title: 'URL', options: [{ value: '$pathname', label: 'Path' }] },
    ]

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
        1200: 'large',
    })

    return (
        <div className={clsx('ErrorTracking__breakdowns grid gap-5', gridColumnsMap[size])} ref={ref}>
            {breakdownGroups.map((group, index) => (
                <BreakdownGroup key={index} group={group} />
            ))}
        </div>
    )
}

const BreakdownGroup = ({ group }: { group: BreakdownGroup }): JSX.Element => {
    const { dateRange, filterTestAccounts, filterGroup } = useValues(errorTrackingLogic)
    const [selectedProperty, setSelectedProperty] = useState<string>(group.options[0].value)

    return (
        <div className="flex flex-col">
            <div className="flex justify-between">
                <h2>{group.title}</h2>
                {group.options.length > 1 && (
                    <LemonSegmentedButton
                        size="xsmall"
                        value={selectedProperty}
                        options={group.options}
                        onChange={setSelectedProperty}
                    />
                )}
            </div>
            <Query
                query={errorTrackingGroupBreakdownQuery({
                    breakdownProperty: selectedProperty,
                    dateRange: dateRange,
                    filterTestAccounts: filterTestAccounts,
                    filterGroup: filterGroup,
                })}
            />
        </div>
    )
}
