import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectProps } from '@posthog/lemon-ui'

import { customerJourneysLogic } from './customerJourneysLogic'

type CustomerJourneySelectProps = Pick<LemonSelectProps<string>, 'type'>

export function CustomerJourneySelect({ type = 'tertiary' }: CustomerJourneySelectProps): JSX.Element | null {
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
            type={type}
            truncateText={{ maxWidthClass: 'max-w-60' }}
        />
    )
}
