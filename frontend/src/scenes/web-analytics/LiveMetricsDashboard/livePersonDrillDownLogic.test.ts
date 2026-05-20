import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { livePersonDrillDownDrawerLogic, LivePersonDrillDownSelection } from './livePersonDrillDownDrawerLogic'
import { COOKIELESS_DISTINCT_ID_PREFIX, partitionDistinctIds } from './livePersonDrillDownLogic'

describe('partitionDistinctIds', () => {
    it('separates cookieless ids from identified ones', () => {
        const result = partitionDistinctIds([
            'user-1',
            `${COOKIELESS_DISTINCT_ID_PREFIX}abc`,
            'user-2',
            `${COOKIELESS_DISTINCT_ID_PREFIX}def`,
        ])
        expect(result).toEqual({
            identified: ['user-1', 'user-2'],
            anonymous: [`${COOKIELESS_DISTINCT_ID_PREFIX}abc`, `${COOKIELESS_DISTINCT_ID_PREFIX}def`],
        })
    })

    it('handles an empty input', () => {
        expect(partitionDistinctIds([])).toEqual({ identified: [], anonymous: [] })
    })

    it('handles all-cookieless input', () => {
        const result = partitionDistinctIds([`${COOKIELESS_DISTINCT_ID_PREFIX}a`, `${COOKIELESS_DISTINCT_ID_PREFIX}b`])
        expect(result.identified).toEqual([])
        expect(result.anonymous).toHaveLength(2)
    })

    it('preserves order within each partition', () => {
        const result = partitionDistinctIds([
            'z',
            `${COOKIELESS_DISTINCT_ID_PREFIX}1`,
            'a',
            `${COOKIELESS_DISTINCT_ID_PREFIX}2`,
            'm',
        ])
        expect(result.identified).toEqual(['z', 'a', 'm'])
        expect(result.anonymous).toEqual([`${COOKIELESS_DISTINCT_ID_PREFIX}1`, `${COOKIELESS_DISTINCT_ID_PREFIX}2`])
    })

    it('does not treat ids that merely contain "cookieless" as anonymous', () => {
        const result = partitionDistinctIds(['user_with_cookieless_word', 'cookieless'])
        expect(result.identified).toEqual(['user_with_cookieless_word', 'cookieless'])
        expect(result.anonymous).toEqual([])
    })
})

describe('livePersonDrillDownDrawerLogic', () => {
    let logic: ReturnType<typeof livePersonDrillDownDrawerLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = livePersonDrillDownDrawerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts with no current selection', async () => {
        await expectLogic(logic).toMatchValues({ currentSelection: null })
    })

    it('opens a drill-down with the given selection', async () => {
        const selection: LivePersonDrillDownSelection = {
            breakdownType: 'country',
            breakdownValue: 'US',
            breakdownLabel: 'United States',
        }
        await expectLogic(logic, () => {
            logic.actions.openDrillDown(selection)
        }).toMatchValues({ currentSelection: selection })
    })

    it('replaces the current selection when opening a different one', async () => {
        logic.actions.openDrillDown({
            breakdownType: 'country',
            breakdownValue: 'US',
            breakdownLabel: 'United States',
        })
        const next: LivePersonDrillDownSelection = {
            breakdownType: 'browser',
            breakdownValue: 'Chrome',
            breakdownLabel: 'Chrome',
        }
        await expectLogic(logic, () => {
            logic.actions.openDrillDown(next)
        }).toMatchValues({ currentSelection: next })
    })

    it('clears the selection on close', async () => {
        logic.actions.openDrillDown({
            breakdownType: 'country',
            breakdownValue: 'US',
            breakdownLabel: 'United States',
        })
        await expectLogic(logic, () => {
            logic.actions.closeDrillDown()
        }).toMatchValues({ currentSelection: null })
    })
})
