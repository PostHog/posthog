import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { customerJourneysLogic } from './customerJourneysLogic'

export function CustomerJourneySelect(): JSX.Element | null {
    const { activeJourneyId, journeyOptions } = useValues(customerJourneysLogic)
    const { setActiveJourneyId } = useActions(customerJourneysLogic)

    if (journeyOptions.length === 0) {
        return null
    }

    return (
        <LemonSelect
            className="border-0"
            value={activeJourneyId}
            onChange={setActiveJourneyId}
            options={journeyOptions}
            size="small"
            type="tertiary"
        />
    )
}
