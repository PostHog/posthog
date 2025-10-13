import { BuiltLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { mockCohort } from '~/test/mocks'
import { CohortType, PropertyFilterType, PropertyOperator } from '~/types'

import { CohortCountWarningLogicProps, cohortCountWarningLogic } from './cohortCountWarningLogic'
import type { cohortCountWarningLogicType } from './cohortCountWarningLogicType'

const createMockQuery = (cohortId: number): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.ActorsQuery,
        fixedProperties: [
            {
                type: PropertyFilterType.Cohort,
                key: 'id',
                value: cohortId,
                operator: PropertyOperator.Exact,
            },
        ],
    },
    full: true,
    showPropertyFilter: false,
    showEventFilter: false,
})

const createMockCohort = (overrides: Partial<CohortType> = {}): CohortType => ({
    ...mockCohort,
    id: 1,
    count: 100,
    is_calculating: false,
    is_static: false,
    ...overrides,
})

describe('cohortCountWarningLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/cohorts': [mockCohort],
                '/api/projects/:team/cohorts/:id': mockCohort,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const createLogicWithProps = (
        props: Partial<CohortCountWarningLogicProps> = {}
    ): BuiltLogic<cohortCountWarningLogicType> => {
        const defaultProps: CohortCountWarningLogicProps = {
            cohort: createMockCohort(),
            query: createMockQuery(1),
            dataNodeLogicKey: 'test-key',
            ...props,
        }
        return cohortCountWarningLogic(defaultProps)
    }

    describe('shouldShowCountWarning selector', () => {
        it('returns false when cohort has no count', () => {
            const cohort = createMockCohort({ count: undefined })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns false when cohort is calculating', () => {
            const cohort = createMockCohort({ is_calculating: true })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns false when cohort is new', () => {
            const cohort = createMockCohort({ id: 'new' })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns false when cohort is static', () => {
            const cohort = createMockCohort({ is_static: true })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns false when there is no response data', () => {
            const logic = createLogicWithProps()
            logic.mount()

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns false when response has more data available', () => {
            const logic = createLogicWithProps()
            logic.mount()

            const mockDataNodeLogic = dataNodeLogic({
                key: 'test-key',
                query: createMockQuery(1),
            })
            mockDataNodeLogic.mount()
            mockDataNodeLogic.actions.loadDataSuccess({
                results: new Array(50),
                hasMore: true,
            })

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns false when displayed count matches cohort count', () => {
            const cohort = createMockCohort({ count: 100 })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            const mockDataNodeLogic = dataNodeLogic({
                key: 'test-key',
                query: createMockQuery(1),
            })
            mockDataNodeLogic.mount()
            mockDataNodeLogic.actions.loadDataSuccess({
                results: new Array(100),
                hasMore: false,
            })

            expect(logic.values.shouldShowCountWarning).toBe(false)
        })

        it('returns true when displayed count does not match cohort count', () => {
            const cohort = createMockCohort({ count: 100 })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            const mockDataNodeLogic = dataNodeLogic({
                key: 'test-key',
                query: createMockQuery(1),
            })
            mockDataNodeLogic.mount()
            mockDataNodeLogic.actions.loadDataSuccess({
                results: new Array(85),
                hasMore: false,
            })

            expect(logic.values.shouldShowCountWarning).toBe(true)
        })

        it('handles empty results array', () => {
            const cohort = createMockCohort({ count: 10 })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            const mockDataNodeLogic = dataNodeLogic({
                key: 'test-key',
                query: createMockQuery(1),
            })
            mockDataNodeLogic.mount()
            mockDataNodeLogic.actions.loadDataSuccess({
                results: [],
                hasMore: false,
            })

            expect(logic.values.shouldShowCountWarning).toBe(true)
        })

        it('handles response without results property', () => {
            const cohort = createMockCohort({ count: 10 })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            const mockDataNodeLogic = dataNodeLogic({
                key: 'test-key',
                query: createMockQuery(1),
            })
            mockDataNodeLogic.mount()
            mockDataNodeLogic.actions.loadDataSuccess({
                hasMore: false,
            })

            expect(logic.values.shouldShowCountWarning).toBe(true)
        })

        it('correctly identifies discrepancy when persons are deleted', () => {
            const cohort = createMockCohort({ count: 150 })
            const logic = createLogicWithProps({ cohort })
            logic.mount()

            const mockDataNodeLogic = dataNodeLogic({
                key: 'test-key',
                query: createMockQuery(1),
            })
            mockDataNodeLogic.mount()
            mockDataNodeLogic.actions.loadDataSuccess({
                results: new Array(120),
                hasMore: false,
            })

            expect(logic.values.shouldShowCountWarning).toBe(true)
        })
    })

    describe('key generation', () => {
        it('generates unique keys based on cohort id and dataNodeLogicKey', () => {
            const props1 = {
                cohort: createMockCohort({ id: 1 }),
                dataNodeLogicKey: 'key1',
                query: createMockQuery(1),
            }
            const props2 = {
                cohort: createMockCohort({ id: 2 }),
                dataNodeLogicKey: 'key1',
                query: createMockQuery(2),
            }
            const props3 = {
                cohort: createMockCohort({ id: 1 }),
                dataNodeLogicKey: 'key2',
                query: createMockQuery(1),
            }

            const logic1 = cohortCountWarningLogic(props1)
            const logic2 = cohortCountWarningLogic(props2)
            const logic3 = cohortCountWarningLogic(props3)

            expect(logic1).not.toBe(logic2)
            expect(logic1).not.toBe(logic3)
            expect(logic2).not.toBe(logic3)
        })
    })

    describe('dataNodeLogic connection', () => {
        it('connects to the correct dataNodeLogic instance', () => {
            const query = createMockQuery(1)
            const dataNodeLogicKey = 'test-cohort-key'

            const logic = createLogicWithProps({
                query,
                dataNodeLogicKey,
            })
            logic.mount()

            expect(logic.props.dataNodeLogicKey).toBe(dataNodeLogicKey)
            expect(logic.props.query).toBe(query)
        })
    })
})
