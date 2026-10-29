import { useActions, useValues } from 'kea'

import { Input } from '@posthog/quill'

import { betsLogic } from '../logics/betsLogic'
import { BetsSelect } from './BetsSelect'

export function BetsFilters(): JSX.Element {
    const { search, status, area, areas, owner, owners } = useValues(betsLogic)
    const { setSearch, setStatus, setArea, setOwner } = useActions(betsLogic)
    const statuses = [
        { value: 'all', label: 'All bets' },
        { value: 'open', label: 'Open bets' },
        { value: 'running', label: 'Running' },
        { value: 'setting_up', label: 'Setting up' },
        { value: 'reached', label: 'Goal reached' },
        { value: 'spent', label: 'Budget used' },
        { value: 'paused', label: 'Paused' },
        { value: 'closed', label: 'Closed' },
    ]
    const people = [
        { value: '', label: 'Any owner' },
        { value: 'me', label: 'Me' },
        ...owners.map((person) => ({ value: String(person.id), label: person.name })),
    ]
    const products = [{ value: '', label: 'All product areas' }, ...areas.map((value) => ({ value, label: value }))]
    return (
        <div className="mb-4 flex flex-wrap items-center gap-2">
            <Input
                aria-label="Search bets"
                placeholder="Search bets…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="w-56 max-w-full"
            />
            <BetsSelect
                value={owner}
                items={people}
                onChange={(value) => setOwner(value ?? '')}
                trigger={{ 'aria-label': 'Owner' }}
            />
            <BetsSelect
                value={status}
                items={statuses}
                onChange={(value) => setStatus(value ?? 'open')}
                trigger={{ 'aria-label': 'Status' }}
            />
            <BetsSelect
                value={area}
                items={products}
                onChange={(value) => setArea(value ?? '')}
                trigger={{ 'aria-label': 'Product area' }}
            />
        </div>
    )
}
