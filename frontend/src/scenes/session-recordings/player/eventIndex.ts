import { eventWithTime } from '@rrweb/types'

interface Metadata {
    playerTime: number
}

interface RecordingPageMetadata extends Metadata {
    href: string
}
interface RecordingScreenMetadata extends Metadata {
    resolution: string
    width: number
    height: number
}

export interface LibCustomEvent {
    type: 5
    data: {
        tag: string
        payload: any
    }
}

export class EventIndex {
    events: eventWithTime[]
    baseTime: number
    _filterByCaches: { [key: string]: any[] }

    constructor(events: eventWithTime[]) {
        this.events = events
        this.baseTime = events.length > 0 ? events[0].timestamp : 0
        this._filterByCaches = {}
    }

    getDuration = (): number =>
        this.events.length > 0 ? this.events[this.events.length - 1].timestamp - this.events[0].timestamp : 0

    getRecordingScreenMetadata = (playerTime: number): [RecordingScreenMetadata, number] | [null, -1] =>
        findCurrent(playerTime, this.recordingScreenMetadata())

    pageChangeEvents = (): RecordingPageMetadata[] =>
        this._filterBy('href', (event) => {
            const eventData = event.data as { href?: string } | undefined

            if (eventData?.href) {
                return {
                    href: (event.data as { href: string }).href,
                    playerTime: event.timestamp - this.baseTime,
                }
            }
            if (event.type === 5 && (event as LibCustomEvent).data.tag === '$pageview') {
                return {
                    href: (event as LibCustomEvent).data.payload.href,
                    playerTime: event.timestamp - this.baseTime,
                }
            }

            return null
        })

    recordingScreenMetadata = (): RecordingScreenMetadata[] =>
        this._filterBy('resolution', (event) => {
            const eventData = event.data as { width?: number; height?: number } | undefined

            if (eventData?.width && eventData?.height) {
                const { width, height } = eventData
                return {
                    resolution: `${width} x ${height}`,
                    height: height,
                    width: width,
                    playerTime: event.timestamp - this.baseTime,
                }
            }
            return null
        })

    _filterBy = <T extends Record<string, V>, V>(dataKey: string, transformer: (e: eventWithTime) => T | null): T[] => {
        if (!this._filterByCaches[dataKey]) {
            let lastValueKey: V | undefined

            this._filterByCaches[dataKey] = this.events.map(transformer).filter((value: T | null) => {
                if (!value) {
                    return false
                }
                if (value[dataKey] !== lastValueKey) {
                    lastValueKey = value[dataKey]
                    return true
                }
                return false
            })
        }
        return this._filterByCaches[dataKey] as T[]
    }
}

export const findCurrent = <T extends Metadata>(playerTime: number, events: T[]): [T, number] | [null, -1] => {
    let index = events.findIndex((event) => event.playerTime > playerTime)

    if (index === 0) {
        return [events[0], 0]
    } else if (index === -1) {
        index = events.length - 1
        return [events[index], index]
    }
    return [events[index - 1], index - 1]
}
