import { createUserTeamAndOrganization, getTeams } from '../helpers/sql'
import { createProcessEventTests } from '../shared/process-event'

jest.setTimeout(600000) // 600 sec timeout.

describe('process event (postgresql)', () => {
    createProcessEventTests('postgresql', {}, (response) => {
        test('element group', async () => {
            const { hub } = response
            const elements = [{ tag_name: 'button', text: 'Sign up!' }, { tag_name: 'div' }]

            const elementsHash = await hub!.db.createElementGroup(elements, 2)
            const elementGroup = await hub!.db.fetchElements()

            expect(elementGroup[0].tag_name).toEqual('button')
            expect(elementGroup[1].tag_name).toEqual('div')
            expect(elementGroup.length).toEqual(2)

            const elements2 = [
                { tag_name: 'button', text: 'Sign up!' },
                // make sure we remove events if we can
                { tag_name: 'div', event: { id: 'blabla' } },
            ]

            const elementsHash2 = await hub!.db.createElementGroup(elements2, 2)
            const elementGroup2 = await hub!.db.fetchElements()
            // we are fetching all the elements, so expect there to be no new ones
            expect(elementGroup2.length).toEqual(2)
            expect(elementsHash).toEqual(elementsHash2)

            await createUserTeamAndOrganization(
                hub!.postgres,
                3,
                1002,
                'a73fc995-a63f-4e4e-bf65-2a5e9f93b2b1',
                '01774e2f-0d01-0000-ee94-9a238640c6ee',
                '0174f81e-36f5-0000-7ef8-cc26c1fbab1c'
            )

            const teams = await getTeams(hub!)

            // # Test no team leakage
            const team2 = teams[1]

            const elementsHash3 = await hub!.db.createElementGroup(elements2, 3)
            const elementGroup3 = await hub!.db.fetchElements()

            // created new elements as it's different team even if the hash is the same
            expect(elementGroup3.length).toEqual(4)
            expect(elementsHash).toEqual(elementsHash2)
            expect(elementsHash).toEqual(elementsHash3)
        })
    })
})
