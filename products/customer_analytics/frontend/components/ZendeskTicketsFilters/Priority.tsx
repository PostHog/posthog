import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { zendeskTicketsFiltersLogic } from './zendeskTicketsFiltersLogic'

export const PriorityFilter = (): JSX.Element => {
    const { priority } = useValues(zendeskTicketsFiltersLogic)
    const { setPriority } = useActions(zendeskTicketsFiltersLogic)

    const options = ['all', 'low', 'normal', 'high', 'urgent']

    const label = (key: string) => {
        switch (key) {
            case 'all':
            case null:
                return 'All priorities'
            default:
                return capitalizeFirstLetter(key)
        }
    }

    return (
        <LemonSelect
            placeholder="Status"
            options={options.map((key) => ({ value: key, label: label(key) }))}
            value={priority}
            onChange={(value) => setPriority(value)}
            size="small"
        />
    )
}
