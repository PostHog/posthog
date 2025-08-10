import { EventType } from '@posthog/rrweb-types'
import posthog from 'posthog-js'

import { RecordingSnapshot } from '~/types'

import { patchMetaEventIntoWebData, ViewportResolution } from './patch-meta-event'
import { clearThrottle } from './throttle-capturing'

describe('patchMetaEventIntoWebData', () => {
    const mockViewportForTimestamp = (): ViewportResolution => ({
        width: '1024',
        height: '768',
        href: 'https://blah.io',
    })

    function createFullSnapshot(): RecordingSnapshot {
        return {
            type: EventType.FullSnapshot,
            timestamp: 1000,
            windowId: 'window1',
            data: {} as any,
        }
    }

    function createMeta(width: number, height: number, href: string = 'https://blah.io'): RecordingSnapshot {
        return {
            type: EventType.Meta,
            timestamp: 1000,
            windowId: 'window1',
            data: {
                width: width,
                height: height,
                href: href,
            },
        }
    }

    it('adds meta event before full snapshot when none exists', () => {
        const snapshots: RecordingSnapshot[] = [createFullSnapshot()]

        const result = patchMetaEventIntoWebData(snapshots, mockViewportForTimestamp, '12345')

        expect(result).toEqual([createMeta(1024, 768), createFullSnapshot()])
    })

    it('does not add meta event if one already exists before full snapshot', () => {
        const snapshots: RecordingSnapshot[] = [createMeta(800, 600, 'http://test'), createFullSnapshot()]

        const result = patchMetaEventIntoWebData(snapshots, mockViewportForTimestamp, '12345')

        expect(result).toHaveLength(2)
        expect(result[0]).toBe(snapshots[0])
        expect(result[1]).toBe(snapshots[1])
    })

    it('handles multiple full snapshots correctly', () => {
        const snapshots: RecordingSnapshot[] = [
            createFullSnapshot(),
            {
                type: EventType.IncrementalSnapshot,
                timestamp: 1500,
                windowId: 'window1',
                data: {},
            } as RecordingSnapshot,
            createFullSnapshot(),
        ]

        const result = patchMetaEventIntoWebData(snapshots, mockViewportForTimestamp, '12345')

        expect(result).toHaveLength(5)
        expect(result[0].type).toBe(EventType.Meta)
        expect(result[1].type).toBe(EventType.FullSnapshot)
        expect(result[2].type).toBe(EventType.IncrementalSnapshot)
        expect(result[3].type).toBe(EventType.Meta)
        expect(result[4].type).toBe(EventType.FullSnapshot)
    })

    it('logs error when viewport dimensions are not available', () => {
        const mockViewportForTimestampNoData = (): ViewportResolution | undefined => undefined
        const snapshots: RecordingSnapshot[] = [createFullSnapshot()]

        jest.spyOn(posthog, 'captureException')

        const result = patchMetaEventIntoWebData(snapshots, mockViewportForTimestampNoData, '12345')

        expect(posthog.captureException).toHaveBeenCalledWith(
            new Error('No event viewport or meta snapshot found for full snapshot'),
            expect.any(Object)
        )
        expect(result).toHaveLength(1)
        expect(result[0]).toBe(snapshots[0])
    })

    it('does not logs error twice for the same session', () => {
        clearThrottle()

        const mockViewportForTimestampNoData = (): ViewportResolution | undefined => undefined
        const snapshots: RecordingSnapshot[] = [createFullSnapshot()]

        jest.spyOn(posthog, 'captureException')

        expect(posthog.captureException).toHaveBeenCalledTimes(0)
        patchMetaEventIntoWebData(snapshots, mockViewportForTimestampNoData, '12345')
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        patchMetaEventIntoWebData(snapshots, mockViewportForTimestampNoData, '12345')
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        patchMetaEventIntoWebData(snapshots, mockViewportForTimestampNoData, '54321')
        expect(posthog.captureException).toHaveBeenCalledTimes(2)
    })
})
