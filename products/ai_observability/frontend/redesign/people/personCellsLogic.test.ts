import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PeopleFirstSeenRequestApi, PersonListApi } from '../../generated/api.schemas'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { ready } from '../traces/testFixtures'
import { peopleListLogic } from './peopleListLogic'
import { personCellsLogic } from './personCellsLogic'
import { PEOPLE_FIRST_SEEN_URL, PEOPLE_URL, makeFirstSeenAnswer, makePersonListPage } from './testFixtures'

const PAGE = makePersonListPage(['person-a', 'person-b'])

describe('personCellsLogic', () => {
    let bodies: PeopleFirstSeenRequestApi[]
    let firstSeenFails: boolean
    let firstSeenHeld: Promise<void> | null
    let thirtyDayPage: PersonListApi
    let logic: ReturnType<typeof personCellsLogic.build>

    async function settle(): Promise<void> {
        await expectLogic(peopleListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        bodies = []
        firstSeenFails = false
        firstSeenHeld = null
        thirtyDayPage = PAGE
        useMocks({
            get: {
                [PEOPLE_URL]: ({ request }) => [
                    200,
                    new URL(request.url).searchParams.get('date_from') === '-30d' ? thirtyDayPage : PAGE,
                ],
            },
            post: {
                [PEOPLE_FIRST_SEEN_URL]: async ({ request }: { request: Request }) => {
                    const body: PeopleFirstSeenRequestApi = await request.json()
                    bodies.push(body)
                    await firstSeenHeld
                    return firstSeenFails
                        ? [500, { detail: 'boom' }]
                        : [200, makeFirstSeenAnswer(body.person_ids, ['person-b'])]
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.aiObservabilityUsers())
        logic = personCellsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it("reads the first seen of the page's people in the page's range", async () => {
        await settle()

        expect(bodies).toEqual([
            { person_ids: ['person-a', 'person-b'], date_from: '-24h', filter_test_accounts: false },
        ])
        expect(logic.values.firstSeen.get('person-b')).toEqual(
            ready({ firstSeen: '2026-11-02T10:00:00Z', checkedFrom: '2026-10-18', isNew: true })
        )
    })

    it('marks the people of a failed read as failed, never as unseen', async () => {
        firstSeenFails = true
        jest.spyOn(posthog, 'captureException')

        await settle()

        expect(['person-a', 'person-b'].map((id) => logic.values.firstSeen.get(id)?.status)).toEqual(['error', 'error'])
    })

    it('drops an answer for the range it left', async () => {
        thirtyDayPage = makePersonListPage(['person-c'])
        let releaseOldRead = (): void => {}
        firstSeenHeld = new Promise((resolve) => {
            releaseOldRead = resolve
        })
        await waitFor(() => expect(bodies).toHaveLength(1))
        firstSeenHeld = null

        shellScopeLogic.actions.setDateRange('-30d', null)
        await waitFor(() => expect(logic.values.firstSeen.get('person-c')?.status).toEqual('ready'))
        releaseOldRead()
        await settle()

        expect([...logic.values.firstSeen.keys()]).toEqual(['person-c'])
    })

    it.each([
        ['the date range changes', () => shellScopeLogic.actions.setDateRange('-30d', null), '-30d'],
        ['the list reloads', () => peopleListLogic.actions.reload(), '-24h'],
    ])('reads the people it has read again when %s', async (_name, change, dateFrom) => {
        await settle()

        change()
        await settle()

        expect(bodies.map((body) => [body.person_ids, body.date_from])).toEqual([
            [['person-a', 'person-b'], '-24h'],
            [['person-a', 'person-b'], dateFrom],
        ])
    })
})
