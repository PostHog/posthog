import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { livePersonDrillDownDrawerLogic, LivePersonDrillDownSelection } from './livePersonDrillDownDrawerLogic'
import {
    aggregateRecordingCountsByPerson,
    COOKIELESS_DISTINCT_ID_PREFIX,
    partitionDistinctIds,
} from './livePersonDrillDownLogic'

const makePerson = (overrides: Partial<PersonType> & { id?: string | number; uuid?: string }): PersonType =>
    ({
        distinct_ids: [],
        properties: {},
        created_at: '2020-01-01T00:00:00Z',
        ...overrides,
    }) as PersonType

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

describe('aggregateRecordingCountsByPerson', () => {
    it("sums counts across each person's distinct_ids", () => {
        const persons = [
            makePerson({ id: 'person-a', distinct_ids: ['d1', 'd2'] }),
            makePerson({ id: 'person-b', distinct_ids: ['d3'] }),
        ]
        const counts = { d1: 2, d2: 3, d3: 1 }
        expect(aggregateRecordingCountsByPerson(persons, counts)).toEqual({
            'person-a': 5,
            'person-b': 1,
        })
    })

    it('omits persons with zero recordings', () => {
        const persons = [
            makePerson({ id: 'person-a', distinct_ids: ['d1'] }),
            makePerson({ id: 'person-b', distinct_ids: ['d2'] }),
        ]
        const counts = { d2: 4 }
        expect(aggregateRecordingCountsByPerson(persons, counts)).toEqual({ 'person-b': 4 })
    })

    it('falls back to uuid when id is missing', () => {
        const persons = [makePerson({ uuid: 'uuid-1', distinct_ids: ['d1'] })]
        expect(aggregateRecordingCountsByPerson(persons, { d1: 7 })).toEqual({ 'uuid-1': 7 })
    })

    it('skips persons with no id and no uuid', () => {
        const persons = [makePerson({ distinct_ids: ['d1'] })]
        expect(aggregateRecordingCountsByPerson(persons, { d1: 1 })).toEqual({})
    })

    it('ignores distinct_ids that are not present in the counts map', () => {
        const persons = [makePerson({ id: 'person-a', distinct_ids: ['d1', 'd-missing'] })]
        expect(aggregateRecordingCountsByPerson(persons, { d1: 2 })).toEqual({ 'person-a': 2 })
    })

    it('returns an empty object when no persons have recordings', () => {
        const persons = [makePerson({ id: 'person-a', distinct_ids: ['d1'] })]
        expect(aggregateRecordingCountsByPerson(persons, {})).toEqual({})
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
