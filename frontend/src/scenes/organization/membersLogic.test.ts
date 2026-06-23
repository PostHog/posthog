import { MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_SECOND_ORGANIZATION_MEMBER, MOCK_USER_UUID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { membersLogic } from './membersLogic'

describe('membersLogic', () => {
    let logic: ReturnType<typeof membersLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/organizations/:organization/members/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [MOCK_SECOND_ORGANIZATION_MEMBER, MOCK_DEFAULT_ORGANIZATION_MEMBER],
                },
            },
        })
        initKeaTests()
        userLogic().mount()
        await expectLogic(userLogic).toMatchValues({ user: expect.objectContaining({ uuid: MOCK_USER_UUID }) })
        logic = membersLogic()
        logic.mount()
    })

    describe('me and otherMembers', () => {
        it('exposes the current user as `me` before the members list loads', async () => {
            await expectLogic(logic).toMatchValues({ members: null })

            expect(logic.values.me?.user.uuid).toEqual(MOCK_USER_UUID)
            expect(logic.values.otherMembers).toEqual([])
            expect(logic.values.meFirstMembers).toEqual([])
        })

        it('keeps `me` and lists everyone else in `otherMembers` once loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadAllMembers()
            }).toFinishAllListeners()

            expect(logic.values.me?.user.uuid).toEqual(MOCK_USER_UUID)
            expect(logic.values.otherMembers.map((member) => member.user.uuid)).toEqual([
                MOCK_SECOND_ORGANIZATION_MEMBER.user.uuid,
            ])
            expect(logic.values.meFirstMembers.map((member) => member.user.uuid)).toEqual([
                MOCK_USER_UUID,
                MOCK_SECOND_ORGANIZATION_MEMBER.user.uuid,
            ])
        })
    })
})
