import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { EventType } from 'posthog-js/rrweb-types'

import { RecordingSnapshot, SessionRecordingType } from '~/types'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { sessionRecordingDataCoordinatorLogic } from './sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { markLoaded } from './snapshot-store/test-utils'
import { snapshotDataLogic } from './snapshotDataLogic'

jest.mock('./snapshot-processing/DecompressionWorkerManager')

const START = new Date('2025-01-01T00:00:00.000Z').valueOf()
const SOURCES = ['8', '9'].map((blobKey, index) => ({
    source: 'blob_v2',
    blob_key: blobKey,
    start_timestamp: new Date(START + index * 60000).toISOString(),
    end_timestamp: new Date(START + (index + 1) * 60000).toISOString(),
}))

const inc = (timestamp: number): RecordingSnapshot =>
    ({ timestamp, type: EventType.IncrementalSnapshot, windowId: 1, data: {} }) as unknown as RecordingSnapshot

describe('PlayerFrameOverlay', () => {
    const props = { sessionRecordingId: '1', playerKey: 'overlay-test' }

    afterEach(() => {
        cleanup()
    })

    // The seek target of a skip-to-matching-event lands in the second (unfetched) source, which is
    // what leaves a modal-opened recording sitting on a frame it can't render yet.
    const mountStalledSkip = (): ReturnType<typeof sessionRecordingPlayerLogic.build> => {
        setupSessionRecordingTest()
        const coordinator = sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '1' })
        coordinator.mount()
        const snapshotLogic = snapshotDataLogic({ sessionRecordingId: '1' })
        snapshotLogic.actions.loadSnapshotSourcesSuccess(SOURCES as any)
        markLoaded(snapshotLogic.cache.store, 0, [inc(START), inc(START + 1000)])
        snapshotLogic.actions.storeUpdated()
        coordinator.actions.setProcessedSnapshots([inc(START), inc(START + 1000)])
        coordinator.actions.loadRecordingMetaSuccess({
            id: '1',
            start_time: new Date(START).toISOString(),
            end_time: new Date(START + 120000).toISOString(),
            recording_duration: 120,
        } as SessionRecordingType)

        const logic = sessionRecordingPlayerLogic(props)
        logic.mount()
        logic.actions.setSkippingToMatchingEvent(true)
        logic.actions.seekToTimestamp(START + 70000, true)
        return logic
    }

    it('offers a way out while a skip to the filtered event is still waiting on data', async () => {
        const logic = mountStalledSkip()

        render(
            <BindLogic logic={sessionRecordingPlayerLogic} props={props}>
                <PlayerFrameOverlay />
            </BindLogic>
        )

        expect(screen.getByText('Skipping to filtered event')).toBeInTheDocument()
        expect(screen.getByText(/Still loading the part of the recording/)).toBeInTheDocument()

        await userEvent.click(screen.getByText('Play from the start'))

        expect(logic.values.isSkippingToMatchingEvent).toBe(false)
        expect(logic.values.skipToFirstMatchingEvent).toBe(false)

        logic.unmount()
    })
})
