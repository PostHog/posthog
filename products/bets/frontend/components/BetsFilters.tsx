import { useActions, useValues } from 'kea'

import { Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { betsLogic } from '../logics/betsLogic'

export function BetsFilters(): JSX.Element {
    const { search, status, area, areas } = useValues(betsLogic)
    const { setSearch, setStatus, setArea } = useActions(betsLogic)
    const statuses = [
        { value: 'open', label: 'Open bets' },
        { value: 'active', label: 'Active' },
        { value: 'preparing', label: 'Preparing' },
        { value: 'paused', label: 'Paused' },
        { value: 'closed', label: 'Closed' },
        { value: 'all', label: 'All bets' },
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
            <Select value={status} items={statuses} onValueChange={(value) => setStatus(value ?? 'open')}>
                <SelectTrigger aria-label="Status">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {statuses.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                            {item.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <Select value={area} items={products} onValueChange={(value) => setArea(value ?? '')}>
                <SelectTrigger aria-label="Product area">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {products.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                            {item.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
