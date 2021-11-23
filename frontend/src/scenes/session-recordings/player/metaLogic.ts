import { kea } from 'kea'
import { metaLogicType } from './metaLogicType'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { eventWithTime } from 'rrweb/typings/types'
import { PersonType } from '~/types'
import { findLastIndex } from 'lib/utils'

const getPersonProperties = (person: Partial<PersonType>, keys: string[]): string | null => {
    if (keys.some((k) => !person?.properties?.[k])) {
        return null
    }
    return keys.map((k) => person?.properties?.[k]).join(', ')
}

export const metaLogic = kea<metaLogicType>({
    path: ['scenes', 'session-recordings', 'player', 'metaLogic'],
    connect: {
        values: [
            sessionRecordingLogic,
            ['sessionPlayerData'],
            sessionRecordingPlayerLogic,
            ['snapshots', 'time', 'scale', 'meta'],
        ],
        actions: [sessionRecordingLogic, ['loadRecordingMetaSuccess']],
    },
    reducers: {
        loading: [
            true,
            {
                loadRecordingMetaSuccess: () => false,
            },
        ],
    },
    selectors: {
        sessionPerson: [
            (selectors) => [selectors.sessionPlayerData],
            (playerData): Partial<PersonType> => {
                return playerData?.person
            },
        ],
        description: [
            (selectors) => [selectors.sessionPerson],
            (person) => {
                const location = getPersonProperties(person, ['$geoip_city_name', '$geoip_country_code'])
                const device = getPersonProperties(person, ['$browser', '$os'])
                return [device, location].filter((s) => s).join(' · ')
            },
        ],
        resolution: [
            (selectors) => [selectors.snapshots, selectors.time],
            (snapshots, time) => {
                // Find snapshot to pull resolution from
                const lastIndex = findLastIndex(snapshots, (s: eventWithTime) => 'width' in s.data)
                if (lastIndex === -1) {
                    return null
                }
                const currIndex = snapshots.findIndex(
                    (s: eventWithTime) => s.timestamp > time.current && 'width' in s.data
                )
                const snapshot = snapshots[currIndex === -1 ? lastIndex : currIndex]
                return {
                    width: snapshot.data.width,
                    height: snapshot.data.height,
                }
            },
        ],
    },
})
