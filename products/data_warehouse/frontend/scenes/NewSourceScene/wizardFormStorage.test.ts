import { clearSourceFormState, restoreSourceFormState, saveSourceFormState } from './wizardFormStorage'

describe('wizardFormStorage', () => {
    beforeEach(() => {
        sessionStorage.clear()
    })

    it('keeps the snapshot on read so a re-mount in the same visit restores it again', () => {
        saveSourceFormState('googlesearchconsole', { google_search_console_integration_id: 42 })

        expect(restoreSourceFormState('googlesearchconsole')).toEqual({ google_search_console_integration_id: 42 })
        // A second read (e.g. after a wizard re-mount) must still return the snapshot.
        expect(restoreSourceFormState('googlesearchconsole')).toEqual({ google_search_console_integration_id: 42 })
    })

    it('drops the snapshot only when the wizard clears it', () => {
        saveSourceFormState('googlesearchconsole', { google_search_console_integration_id: 42 })
        clearSourceFormState('googlesearchconsole')

        expect(restoreSourceFormState('googlesearchconsole')).toBeNull()
    })
})
