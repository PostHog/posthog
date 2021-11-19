import { kea } from 'kea'
import { metaLogicType } from './metaLogicType'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { eventWithTime } from 'rrweb/typings/types'
import { PersonType } from '~/types'

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
        currentSnapshot: [
            (selectors) => [selectors.snapshots, selectors.time],
            (snapshots, time): eventWithTime | null => {
                const index = snapshots.findIndex((s: eventWithTime) => s.timestamp > time.current && 'width' in s.data)
                if (index === -1) {
                    return null
                }
                return snapshots[index]
            },
        ],
        resolution: [
            (selectors) => [selectors.currentSnapshot],
            (snapshot) => {
                if (!(snapshot && 'width' in snapshot.data && 'height' in snapshot.data)) {
                    return null
                }
                return {
                    width: snapshot.data.width,
                    height: snapshot.data.height,
                }
            },
        ],
    },
})
