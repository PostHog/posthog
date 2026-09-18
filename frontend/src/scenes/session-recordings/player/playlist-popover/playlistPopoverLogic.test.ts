import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingPlaylistType } from '~/types'

import { playlistPopoverLogic } from './playlistPopoverLogic'

describe('playlistPopoverLogic', () => {
    let logic: ReturnType<typeof playlistPopoverLogic.build>
    const collection = { id: 1, short_id: 'abc', name: 'My collection' } as SessionRecordingPlaylistType

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists': { results: [], count: 0 },
            },
        })
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        logic = playlistPopoverLogic({ sessionRecordingId: 'rec-1', playerKey: 'test' })
        logic.mount()
    })

    // A status-less failure is what `handleFetch` throws when the request path itself faults, and
    // the generic loader toast in initKea only fires when `status` is set. Without these listeners
    // the popover row completes nothing and says nothing.
    it.each([
        ['addToPlaylist', 'addRecordingToPlaylist' as const, 'Failed to add to collection'],
        ['removeFromPlaylist', 'removeRecordingFromPlaylist' as const, 'Failed to remove from collection'],
    ])('toasts once when %s fails without a status', async (action, apiMethod, expectedPrefix) => {
        jest.spyOn(api.recordings, apiMethod).mockRejectedValue(new ApiError('You cannot edit this collection.'))

        logic.actions[action as 'addToPlaylist' | 'removeFromPlaylist'](collection)

        await expectLogic(logic).toDispatchActions([`${action}Failure`])
        expect(lemonToast.error).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).toHaveBeenCalledWith(`${expectedPrefix}: You cannot edit this collection.`)
    })
})
