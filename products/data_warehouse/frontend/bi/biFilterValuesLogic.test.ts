import { expectLogic } from 'kea-test-utils'

import * as queryRunner from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biFilterValuesLogic } from './biFilterValuesLogic'

describe('BI filter suggestions', () => {
    beforeEach(() => initKeaTests())

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
