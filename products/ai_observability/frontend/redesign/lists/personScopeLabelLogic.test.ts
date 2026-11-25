import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PersonListItemApi } from '../../generated/api.schemas'
import { PERSON_URL, makePersonListItem } from '../people/testFixtures'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { personScopeLabelLogic } from './personScopeLabelLogic'

const PERSON_ID = '0192f3c9-0000-7000-8000-0000000000aa'

describe('personScopeLabelLogic', () => {
    let reads: Record<string, string>[]
    let logic: ReturnType<typeof personScopeLabelLogic.build>

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each<[string, [number, PersonListItemApi | { detail: string }], string | null]>([
        [
            "the person's row",
            [
                200,
                makePersonListItem({ id: PERSON_ID, person: { distinctId: 'ana@example.com', label: 'Ana Example' } }),
            ],
            PERSON_ID,
        ],
        ['no row when the range does not hold them', [404, { detail: 'Not found.' }], null],
        ['no row when the read fails', [500, { detail: 'boom' }], null],
    ])("reads the person in the shell's range and gives %s", async (_name, answer, personId) => {
        jest.spyOn(posthog, 'captureException')
        reads = []
        useMocks({
            get: {
                [PERSON_URL]: ({ request, params }) => {
                    reads.push({
                        id: String(params.person_id),
                        ...Object.fromEntries(new URL(request.url).searchParams),
                    })
                    return answer
                },
            },
        })
        initKeaTests()
        localStorage.clear()
        shellScopeLogic.mount()
        shellScopeLogic.actions.setDateRange('-30d', null)

        logic = personScopeLabelLogic({ personId: PERSON_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(reads).toEqual([{ id: PERSON_ID, date_from: '-30d', filter_test_accounts: 'false' }])
        expect(logic.values.person?.id ?? null).toEqual(personId)
    })
})
