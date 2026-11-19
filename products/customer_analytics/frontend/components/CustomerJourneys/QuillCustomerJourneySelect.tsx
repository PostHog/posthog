import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { customerJourneysLogic } from './customerJourneysLogic'

export function QuillCustomerJourneySelect(): JSX.Element | null {
    const { activeJourneyId, journeys } = useValues(customerJourneysLogic)
    const { setActiveJourneyId } = useActions(customerJourneysLogic)

    if (journeys.length === 0) {
        return null
    }

    const items = journeys.map((journey) => ({ value: journey.id, label: journey.name }))

    return (
        <Select<string>
            items={items}
            value={activeJourneyId}
            onValueChange={(value) => {
                if (value) {
                    setActiveJourneyId(value)
                }
            }}
        >
            <SelectTrigger className="max-w-60">
                <SelectValue className="truncate" />
            </SelectTrigger>
            <SelectContent>
                {items.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                        {item.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
