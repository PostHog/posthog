import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { zendeskTicketsFiltersLogic } from './zendeskTicketsFiltersLogic'

const label = (key: string) => {
    switch (key) {
        case 'updated_at':
            return 'Updated'
        case 'created_at':
            return 'Created'
        default:
            return capitalizeFirstLetter(key)
    }
}

export const OrderBy = (): JSX.Element => {
    const { orderBy, orderDirection } = useValues(zendeskTicketsFiltersLogic)
    const { setOrderBy, setOrderDirection } = useActions(zendeskTicketsFiltersLogic)

    const options = ['updated_at', 'created_at']

    return (
        <div className="flex flex-row gap-1 items-center">
            <span>Sort by:</span>
            <LemonSelect
                placeholder="Order by"
                options={options.map((key) => ({ value: key, label: label(key) }))}
                value={orderBy}
                onChange={(value) => setOrderBy(value)}
                size="small"
            />
            <LemonSelect
                placeholder="Direction"
                options={[
                    { value: 'asc', label: 'Ascending' },
                    { value: 'desc', label: 'Descending' },
                ]}
                value={orderDirection}
                onChange={(value) => setOrderDirection(value)}
                size="small"
            />
        </div>
    )
}
