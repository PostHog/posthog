import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { todayPreviewCardLogic } from './todayPreviewCardLogic'

const privateSpace = { id: 'space-1', channel_type: 'private', system_role: null } as ChannelDTOApi
const member = { id: 1, first_name: 'Ada', last_name: '', email: 'ada@example.com' }

describe('todayPreviewCardLogic', () => {
    let membersLoad: boolean

    beforeEach(() => {
        membersLoad = false
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/:id/members/': () =>
                    membersLoad ? [200, [member]] : [500, { detail: 'Server error' }],
            },
        })
        initKeaTests()
    })

    it('loads the members again when the card opens after a failed load', async () => {
        const logic = todayPreviewCardLogic()
        logic.mount()

        await expectLogic(logic, () =>
            logic.actions.previewOpened({ kind: 'space', space: privateSpace })
        ).toFinishAllListeners()
        expect(logic.values.spaceMembers).toEqual({})
        expect(logic.values.failedSpaceMemberIds).toEqual(['space-1'])

        membersLoad = true
        await expectLogic(logic, () =>
            logic.actions.previewOpened({ kind: 'space', space: privateSpace })
        ).toFinishAllListeners()
        expect(logic.values.spaceMembers).toEqual({ 'space-1': [member] })
        expect(logic.values.failedSpaceMemberIds).toEqual([])
    })
})
