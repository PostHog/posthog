import {
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_USER,
    MOCK_SECOND_ORGANIZATION_MEMBER,
    MOCK_USER_UUID,
} from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
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

    describe('selectableMembers', () => {
        it('offers just the current user before the list loads', async () => {
            await expectLogic(logic).toMatchValues({ members: null })

            expect(logic.values.selectableMembers().map((member) => member.user.uuid)).toEqual([MOCK_USER_UUID])
        })

        it('puts the current user first and excludes the given members once loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadAllMembers()
            }).toFinishAllListeners()

            expect(logic.values.selectableMembers().map((member) => member.user.uuid)).toEqual([
                MOCK_USER_UUID,
                MOCK_SECOND_ORGANIZATION_MEMBER.user.uuid,
            ])
            expect(
                logic.values
                    .selectableMembers([MOCK_SECOND_ORGANIZATION_MEMBER.user.id], 'id')
                    .map((member) => member.user.uuid)
            ).toEqual([MOCK_USER_UUID])
        })

        it('drops the current user and returns the searched members while searching', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadAllMembers()
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setSearch('Rose')
            }).toDispatchActions(['loadSearchedMembersSuccess'])

            const result = logic.values.selectableMembers().map((member) => member.user.uuid)
            expect(result).not.toContain(MOCK_USER_UUID)
            expect(result).toContain(MOCK_SECOND_ORGANIZATION_MEMBER.user.uuid)
        })
    })

    describe('postRemoveMember', () => {
        beforeEach(() => {
            silenceKeaLoadersErrors()
        })

        afterEach(() => {
            resumeKeaLoadersErrors()
        })

        it.each([200, 503, 0])('preserves the member removal when the user refresh returns %s', async (status) => {
            organizationLogic.mount()
            await expectLogic(organizationLogic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            await expectLogic(logic, () => {
                logic.actions.loadAllMembers()
            }).toFinishAllListeners()

            expect(logic.values.memberCount).toBe(2)
            const updatedOrganization = { ...MOCK_DEFAULT_ORGANIZATION, member_count: 1 }
            useMocks({
                get: {
                    '/api/organizations/@current/': updatedOrganization,
                    '/api/users/@me/': () =>
                        status === 0
                            ? HttpResponse.error()
                            : [status, { ...MOCK_DEFAULT_USER, organization: updatedOrganization }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.postRemoveMember(MOCK_SECOND_ORGANIZATION_MEMBER.user.uuid)
            }).toFinishAllListeners()

            expect(logic.values.members).toEqual([MOCK_DEFAULT_ORGANIZATION_MEMBER])
            expect(organizationLogic.values.currentOrganization?.member_count).toBe(1)
            expect(userLogic.values.user?.uuid).toBe(MOCK_USER_UUID)
            expect(userLogic.values.user?.organization?.member_count).toBe(status === 200 ? 1 : 2)
            expect(logic.values.memberCount).toBe(status === 200 ? 1 : 2)
        })
    })
})
