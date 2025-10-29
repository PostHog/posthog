import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { zendeskTicketsFiltersLogic } from './zendeskTicketsFiltersLogic'

const label = (key: string) => {
    switch (key) {
        case 'all':
        case null:
            return 'All priorities'
        default:
            return capitalizeFirstLetter(key)
    }
}

export const PriorityFilter = (): JSX.Element => {
    const { priority } = useValues(zendeskTicketsFiltersLogic)
    const { setPriority } = useActions(zendeskTicketsFiltersLogic)

    const options = ['all', 'low', 'normal', 'high', 'urgent']

    return (
        <LemonSelect
            placeholder="Priority"
            options={options.map((key) => ({ value: key, label: label(key) }))}
            value={priority}
            onChange={(value) => setPriority(value)}
            size="small"
        />
    )
}
