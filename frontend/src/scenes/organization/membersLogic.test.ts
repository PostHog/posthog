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

    describe('meFirstMembers', () => {
        it('returns the current user as a synthetic entry before the list loads', async () => {
            await expectLogic(logic).toMatchValues({ members: null })

            expect(logic.values.meFirstMembers).toHaveLength(1)
            expect(logic.values.meFirstMembers[0].user.uuid).toEqual(MOCK_USER_UUID)
        })

        it('returns the real members with the current user first once loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadAllMembers()
            }).toFinishAllListeners()

            expect(logic.values.meFirstMembers.map((member) => member.user.uuid)).toEqual([
                MOCK_USER_UUID,
                MOCK_SECOND_ORGANIZATION_MEMBER.user.uuid,
            ])
        })
    })
})
