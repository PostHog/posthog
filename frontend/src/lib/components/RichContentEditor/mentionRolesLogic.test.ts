import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mentionRolesLogic } from './mentionRolesLogic'

describe('mentionRolesLogic', () => {
    it('loads every page of the organization roles', async () => {
        const roles = Array.from({ length: 250 }, (_, index) => ({ id: `role-${index}`, name: `Role ${index}` }))
        useMocks({
            get: {
                '/api/organizations/:organization_id/roles/': ({ request }) => {
                    const url = new URL(request.url)
                    const limit = Number(url.searchParams.get('limit'))
                    const offset = Number(url.searchParams.get('offset'))
                    const page = roles.slice(offset, offset + limit)
                    const next = offset + limit < roles.length ? `${url.pathname}?offset=${offset + limit}` : null
                    return [200, { count: roles.length, next, previous: null, results: page }]
                },
            },
        })
        initKeaTests()

        const logic = mentionRolesLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadRolesSuccess'])

        expect(logic.values.roles.map((role) => role.id)).toEqual(roles.map((role) => role.id))
    })
})
