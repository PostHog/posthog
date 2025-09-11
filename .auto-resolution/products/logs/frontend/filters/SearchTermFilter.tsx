import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { logsLogic } from '../logsLogic'

export const SearchTermFilter = (): JSX.Element => {
    const { searchTerm } = useValues(logsLogic)
    const { setSearchTerm } = useActions(logsLogic)

    return (
        <span className="rounded bg-surface-primary">
            <LemonInput
                size="small"
                value={searchTerm}
                onChange={(value) => setSearchTerm(value)}
                placeholder="Search logs..."
            />
        </span>
    )
}
