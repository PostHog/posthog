import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { COMPOSE_PERSON_URL_PARAM, composeTicketLogic } from './composeTicketLogic'

const PERSON_UUID = '01890000-0000-0000-0000-000000000001'

describe('composeTicketLogic', () => {
    let personGate: Promise<void>
    let releasePerson: () => void
    let personRequested: boolean

    beforeEach(() => {
        personGate = Promise.resolve()
        releasePerson = () => {}
        personRequested = false
        useMocks({
            get: {
                '/api/conversations/v1/email/status': () => [200, { configs: [] }],
                [`/api/projects/:team_id/persons/${PERSON_UUID}/`]: async () => {
                    personRequested = true
                    await personGate
                    return [
                        200,
                        {
                            id: 1,
                            uuid: PERSON_UUID,
                            name: 'Test person',
                            distinct_ids: ['distinct-1', 'distinct-2'],
                            properties: { email: 'person@example.com' },
                            created_at: '2026-01-01T00:00:00Z',
                            last_seen_at: null,
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    function mountAtComposeLink(): ReturnType<typeof composeTicketLogic.build> {
        router.actions.push(urls.supportTickets(), { [COMPOSE_PERSON_URL_PARAM]: PERSON_UUID, status: 'open' })
        const logic = composeTicketLogic()
        logic.mount()
        return logic
    }

    it('opens the composer prefilled from a compose_person link and removes the param', async () => {
        const logic = mountAtComposeLink()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            isOpen: true,
            recipientDistinctId: 'distinct-1',
            recipientEmail: 'person@example.com',
        })
        expect(router.values.searchParams).toEqual({ status: 'open' })
    })

    it.each([
        [
            'the composer closes and a new draft opens',
            (logic: ReturnType<typeof composeTicketLogic.build>) => {
                logic.actions.closeComposeModal()
                logic.actions.openComposeModal()
            },
            '',
        ],
        [
            'the user enters a different recipient',
            (logic: ReturnType<typeof composeTicketLogic.build>) => {
                logic.actions.setRecipientEmail('typed@example.com')
            },
            'typed@example.com',
        ],
    ])('ignores a late person lookup when %s', async (_name, interrupt, expectedEmail) => {
        personGate = new Promise<void>((resolve) => {
            releasePerson = resolve
        })
        const logic = mountAtComposeLink()
        await waitFor(() => expect(personRequested).toBe(true))

        interrupt(logic)
        releasePerson()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            isOpen: true,
            recipientDistinctId: '',
            recipientEmail: expectedEmail,
        })
    })
})
