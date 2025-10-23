import { actions, kea, listeners, path, reducers } from 'kea'

import type { sessionRecordingPinnedPropertiesLogicType } from './sessionRecordingPinnedPropertiesLogicType'

export const sessionRecordingPinnedPropertiesLogic = kea<sessionRecordingPinnedPropertiesLogicType>([
    path(['scenes', 'session-recordings', 'player', 'playerMetaLogic', 'sessionRecordingPinnedPropertiesLogic']),
    actions({
        setPinnedProperties: (properties: string[]) => ({ properties }),
        togglePropertyPin: (propertyKey: string) => ({ propertyKey }),
    }),
    reducers({
        pinnedProperties: [
            [
                'Start',
                'Clicks',
                'Duration',
                'TTL',
                'click_count',
                'keypress_count',
                'console_error_count',
                '$referrer',
                '$geoip_country_code',
                '$geoip_city_name',
            ] as string[],
            { persist: true },
            {
                setPinnedProperties: (_, { properties }) => properties,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        togglePropertyPin: ({ propertyKey }) => {
            const currentPinned = values.pinnedProperties
            if (currentPinned.includes(propertyKey)) {
                actions.setPinnedProperties(currentPinned.filter((k) => k !== propertyKey))
            } else {
                actions.setPinnedProperties([...currentPinned, propertyKey])
            }
        },
    })),
])
