import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { recordings } from 'scenes/session-recordings/__mocks__/recordings'

import { initKeaTests } from '~/test/init'

import { SessionRecordingPreview } from './SessionRecordingPreview'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

describe('SessionRecordingPreview', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // Mounting the keyed playlist logic mid-render throws and takes down the whole scene, so a
    // preview outside a playlist must never reach for it. Only the selection checkbox may.
    it('renders outside a playlist without mounting the playlist logic', () => {
        render(<SessionRecordingPreview recording={recordings[0]} />)

        expect(screen.getByText('test@posthog.com')).toBeInTheDocument()
        // 1172.675s of recording_duration, the column the default start_time order shows
        expect(screen.getByText('19:32')).toBeInTheDocument()
        expect(sessionRecordingsPlaylistLogic.isMounted({})).toBe(false)
    })
})
