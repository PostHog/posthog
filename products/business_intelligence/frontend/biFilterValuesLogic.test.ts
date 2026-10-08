import { expectLogic } from 'kea-test-utils'

import * as queryRunner from '~/queries/query'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biFilterValuesLogic } from 'products/business_intelligence/frontend/biFilterValuesLogic'

describe('BI filter suggestions', () => {
    beforeEach(() => initKeaTests())

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
        await expectLogic(logic, () => logic.actions.setSearch("O'Reilly")).toFinishAllListeners()
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
