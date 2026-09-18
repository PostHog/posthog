import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { recordings } from 'scenes/session-recordings/__mocks__/recordings'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SessionRecordingPreview } from './SessionRecordingPreview'
import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

describe('SessionRecordingPreview', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>

    const logicProps = { logicKey: 'preview-component-test', updateSearchParams: false }
    const recording = recordings[0]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': { results: [], has_next: false },
                '/api/environments/:team_id/session_recordings/properties': { results: [] },
            },
        })
        initKeaTests()
        logic = sessionRecordingsPlaylistLogic(logicProps)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        localStorage.clear()
    })

    function renderPreview(): ReturnType<typeof render> {
        return render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                    <SessionRecordingPreview recording={recording} selectable />
                </BindLogic>
            </Provider>
        )
    }

    it('only offers the row for notebook drag while alt is held', () => {
        const { container } = renderPreview()
        const draggable = container.querySelector('.DraggableToNotebook')

        expect(draggable).toHaveAttribute('draggable', 'false')

        fireEvent.keyDown(window, { key: 'Alt' })
        expect(container.querySelector('.DraggableToNotebook')).toHaveAttribute('draggable', 'true')

        fireEvent.blur(window)
        expect(container.querySelector('.DraggableToNotebook')).toHaveAttribute('draggable', 'false')
    })

    it('can still deselect a recording once the selection cap is reached', () => {
        const otherIds = Array.from({ length: MAX_SELECTED_RECORDINGS - 1 }, (_, i) => `other-${i}`)
        logic.actions.setSelectedRecordingsIds([...otherIds, recording.id])

        const { container } = renderPreview()
        const checkbox = container.querySelector('[data-attr="select-recording"] input') as HTMLInputElement
        expect(checkbox).toBeEnabled()

        fireEvent.click(checkbox)
        expect(logic.values.selectedRecordingsIds).toEqual(otherIds)
    })
})
