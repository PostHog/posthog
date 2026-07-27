import { MOCK_DEFAULT_BASIC_USER, MOCK_SECOND_BASIC_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { setupSessionRecordingTest } from '../__mocks__/test-setup'
import { playerCommentOverlayLogic } from './playerFrameCommentOverlayLogic'

jest.mock('../snapshot-processing/DecompressionWorkerManager')

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist', recordingId: '1' }

const mockMembers = [
    {
        id: '1',
        user: MOCK_DEFAULT_BASIC_USER,
        level: 8,
        joined_at: '2020-09-24T15:05:26.758796Z',
        updated_at: '2020-09-24T15:05:26.758837Z',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: '2020-09-24T15:05:26.758796Z',
    },
    {
        id: '2',
        user: MOCK_SECOND_BASIC_USER,
        level: 1,
        joined_at: '2021-03-11T19:11:11Z',
        updated_at: '2021-03-11T19:11:11Z',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: '2021-03-11T19:11:11Z',
    },
]

describe('playerFrameCommentOverlayLogic', () => {
    let logic: ReturnType<typeof playerCommentOverlayLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            getMocks: {
                '/api/organizations/:organization_id/members/': { results: mockMembers },
            },
        })
        featureFlagLogic.mount()

        sessionRecordingPlayerLogic(playerLogicProps).mount()

        logic = playerCommentOverlayLogic(playerLogicProps)
        logic.mount()
    })

    // Regression test: opening the in-player comment box must populate the org
    // members list so the @-mention autocomplete can resolve teammates. Without
    // this, deep-linking straight to the player and commenting showed an empty
    // "No member matching @" list because nothing else had loaded members yet.
    it('loads org members when the comment overlay opens', async () => {
        await expectLogic(membersLogic, () => {
            logic.actions.setIsCommenting(true)
        }).toDispatchActions(['ensureAllMembersLoaded', 'loadAllMembers', 'loadAllMembersSuccess'])

        expect(membersLogic.values.meFirstMembers).toHaveLength(mockMembers.length)
    })

    it('does not load all members again when the overlay closes', async () => {
        // Prime the loaded state first so the close path is exercised in isolation.
        await expectLogic(membersLogic, () => {
            logic.actions.setIsCommenting(true)
        }).toDispatchActions(['loadAllMembersSuccess'])

        await expectLogic(membersLogic, () => {
            logic.actions.setIsCommenting(false)
        }).toNotHaveDispatchedActions(['loadAllMembers'])
    })
})
