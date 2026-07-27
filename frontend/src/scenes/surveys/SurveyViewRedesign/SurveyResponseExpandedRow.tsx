import { EventDetails } from 'scenes/activity/explore/EventDetails'

import { EventType } from '~/types'

function findEventInRow(result: unknown): EventType | null {
    if (!Array.isArray(result)) {
        return null
    }
    for (const cell of result) {
        if (
            cell &&
            typeof cell === 'object' &&
            !Array.isArray(cell) &&
            'properties' in cell &&
            typeof (cell as { properties: unknown }).properties === 'object'
        ) {
            return cell as EventType
        }
    }
    return null
}

export function SurveyResponseExpandedRow({ result }: { result: unknown }): JSX.Element | null {
    const event = findEventInRow(result)
    if (!event) {
        return null
    }
    return <EventDetails event={event} />
}
