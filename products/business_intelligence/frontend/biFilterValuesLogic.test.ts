import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import * as queryRunner from '~/queries/query'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biFilterValuesLogic } from 'products/business_intelligence/frontend/biFilterValuesLogic'

describe('BI filter suggestions', () => {
    beforeEach(() => initKeaTests())

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('cancels a pending value lookup on replacement and unmount without cancelling completed queries', async () => {
        const requests: AbortSignal[] = []
        const performQuery = jest.spyOn(queryRunner, 'performQuery').mockImplementation(
            (_query, options) =>
                new Promise((_resolve, reject) => {
                    const signal = options!.signal!
                    requests.push(signal)
                    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
                })
        )
        const cancelQuery = jest.spyOn(api, 'cancelQuery').mockResolvedValue(undefined)
        const logic = biFilterValuesLogic({
            query: { kind: NodeKind.HogQLQuery, query: 'SELECT DISTINCT name AS value FROM accounts' },
            active: true,
        })
        const unmount = logic.mount()
        expect(requests).toHaveLength(1)
        jest.useFakeTimers()
        await expectLogic(logic, () => logic.actions.setSearch('new')).toDispatchActions(['loadOptions'])
        expect(requests[0].aborted).toBe(true)
        expect(cancelQuery).toHaveBeenCalledWith(performQuery.mock.calls[0][3])
        await jest.advanceTimersByTimeAsync(300)
        expect(requests).toHaveLength(2)
        unmount()
        expect(requests.every((signal) => signal.aborted)).toBe(true)
        expect(cancelQuery).toHaveBeenCalledTimes(requests.length)

        jest.useRealTimers()
        performQuery.mockResolvedValue({ results: [['done']] } as never)
        const completed = biFilterValuesLogic({
            query: { kind: NodeKind.HogQLQuery, query: 'SELECT DISTINCT region AS value FROM accounts' },
            active: true,
        })
        completed.mount()
        await expectLogic(completed).toDispatchActions(['loadOptionsSuccess'])
        completed.unmount()
        expect(cancelQuery).toHaveBeenCalledTimes(requests.length)
    })

    it('paginates beyond 100 values, searches on the server, and resets pagination for a new search', async () => {
        const performQuery = jest
            .spyOn(queryRunner, 'performQuery')
            .mockResolvedValueOnce({ results: Array.from({ length: 101 }, (_, index) => [`value ${index}`]) } as never)
            .mockResolvedValueOnce({ results: [['value 100']] } as never)
            .mockResolvedValueOnce({ results: [["O'Reilly"]] } as never)
        const logic = biFilterValuesLogic({
            query: { kind: NodeKind.HogQLQuery, query: 'SELECT DISTINCT name AS value FROM accounts' },
            active: true,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadOptionsSuccess'])
        expect(logic.values.options).toHaveLength(100)
        expect(logic.values.hasMore).toBe(true)
        await expectLogic(logic, () => logic.actions.loadMore()).toFinishAllListeners()
        expect(logic.values.options).toHaveLength(101)
        expect(logic.values.hasMore).toBe(false)
        expect((performQuery.mock.calls[1][0] as HogQLQuery).query).toContain('OFFSET 100')
        await expectLogic(logic, () => logic.actions.setSearch('')).toFinishAllListeners()
        expect(performQuery).toHaveBeenCalledTimes(2)
        expect(logic.values.options).toHaveLength(101)
        logic.actions.setSearch("O'Reilly")
        expect(logic.values.options).toHaveLength(101)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.options).toEqual(["O'Reilly"])
        expect((performQuery.mock.calls[2][0] as HogQLQuery).query).toContain(
            "positionCaseInsensitiveUTF8(value, 'O\\'Reilly')"
        )
        expect((performQuery.mock.calls[2][0] as HogQLQuery).query).toContain('OFFSET 0')
        logic.unmount()
        performQuery.mockRestore()
    })

    it('loads a changed query while the input remains focused', async () => {
        const query = { kind: NodeKind.HogQLQuery as const, query: 'SELECT DISTINCT event FROM events LIMIT 100' }
        const performQuery = jest
            .spyOn(queryRunner, 'performQuery')
            .mockResolvedValue({ results: [['first']] } as never)
        const initial = biFilterValuesLogic({ query, active: false })
        initial.mount()
        expect(performQuery).not.toHaveBeenCalled()
        await expectLogic(initial, () => {
            biFilterValuesLogic({ query, active: true })
        }).toFinishAllListeners()
        expect(initial.values.options).toEqual(['first'])
        initial.unmount()

        performQuery.mockResolvedValue({ results: [['second']] } as never)
        const changed = biFilterValuesLogic({ query: { ...query, query: `${query.query} OFFSET 1` }, active: true })
        changed.mount()
        await expectLogic(changed).toDispatchActions(['loadOptionsSuccess'])
        expect(changed.values.options).toEqual(['second'])
        changed.unmount()
        performQuery.mockRestore()
    })
})
