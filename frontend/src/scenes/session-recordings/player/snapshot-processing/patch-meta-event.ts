import posthog from 'posthog-js'

import { eventWithTime } from '@posthog/rrweb-types'
import { fullSnapshotEvent } from '@posthog/rrweb-types'
import { EventType } from '@posthog/rrweb-types'

import { isObject } from 'lib/utils'

import { RecordingSnapshot } from '~/types'

import { throttleCapture } from './throttle-capturing'

export interface ViewportResolution {
    width: string
    height: string
    href: string
}

export const getHrefFromSnapshot = (snapshot: unknown): string | undefined => {
    return isObject(snapshot) && 'data' in snapshot
        ? (snapshot.data as any)?.href || (snapshot.data as any)?.payload?.href
        : undefined
}

/*
 there was a bug in mobile SDK that didn't consistently send a meta event with a full snapshot.
 rrweb player hides itself until it has seen the meta event 🤷
 but we can patch a meta event into the recording data to make it work
*/
export function patchMetaEventIntoMobileData(
    parsedLines: RecordingSnapshot[],
    sessionRecordingId: string
): RecordingSnapshot[] {
    let fullSnapshotIndex: number = -1
    let metaIndex: number = -1
    try {
        fullSnapshotIndex = parsedLines.findIndex((l) => l.type === EventType.FullSnapshot)
        metaIndex = parsedLines.findIndex((l) => l.type === EventType.Meta)

        // then we need to patch the meta event into the snapshot data
        if (fullSnapshotIndex > -1 && metaIndex === -1) {
            const fullSnapshot = parsedLines[fullSnapshotIndex] as RecordingSnapshot & fullSnapshotEvent & eventWithTime
            // a full snapshot (particularly from the mobile transformer) has a relatively fixed structure,
            // but the types exposed by rrweb don't quite cover what we need , so...
            const mainNode = fullSnapshot.data.node as any
            const targetNode = mainNode.childNodes[1].childNodes[1].childNodes[0]
            const { width, height } = targetNode.attributes
            const metaEvent: RecordingSnapshot = {
                windowId: fullSnapshot.windowId,
                type: EventType.Meta,
                timestamp: fullSnapshot.timestamp,
                data: {
                    href: getHrefFromSnapshot(fullSnapshot) || '',
                    width,
                    height,
                },
            }
            parsedLines.splice(fullSnapshotIndex, 0, metaEvent)
        }
    } catch (e) {
        throttleCapture(`${sessionRecordingId}-missing-mobile-meta-patching`, () => {
            posthog.captureException(e, {
                tags: { feature: 'session-recording-missing-mobile-meta-patching' },
                extra: { fullSnapshotIndex, metaIndex },
            })
        })
    }

    return parsedLines
}
