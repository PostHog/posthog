import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sessionsAvailabilityLogic } from './sessionsAvailabilityLogic'

const AVAILABILITY_URL = '/api/projects/:team_id/ai_observability/sessions/availability/'

describe('sessionsAvailabilityLogic', () => {
    let logic: ReturnType<typeof sessionsAvailabilityLogic.build>
    let reads: number

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each<[string, [number, unknown], boolean | null]>([
        ['the project has sessions', [200, { hasSessions: true }], true],
        ['the project has none', [200, { hasSessions: false }], false],
        ['the probe fails', [500, { detail: 'boom' }], null],
    ])('reads once on mount and answers when %s', async (_name, answer, expected) => {
        reads = 0
        useMocks({
            get: {
                [AVAILABILITY_URL]: () => {
                    reads += 1
                    return answer
                },
            },
        })
        initKeaTests()
        const toastError = jest.spyOn(lemonToast, 'error')
        logic = sessionsAvailabilityLogic()

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        sessionsAvailabilityLogic().mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasSessions).toBe(expected)
        expect(reads).toBe(1)
        expect(toastError).not.toHaveBeenCalled()
    })
})
