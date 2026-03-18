import { initKeaTests } from '~/test/init'

import { propertyFilterBetweenLogic } from './propertyFilterBetweenLogic'

describe('propertyFilterBetweenLogic', () => {
    let logic: ReturnType<typeof propertyFilterBetweenLogic.build>
    let mockOnSet: jest.Mock

    beforeEach(() => {
        initKeaTests()
        mockOnSet = jest.fn()
    })

    describe('initialization', () => {
        it('initializes with null values when value is null', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: null,
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBeNull()
            expect(logic.values.localMax).toBeNull()
        })

        it('initializes with numeric values from array', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBe(10)
            expect(logic.values.localMax).toBe(20)
        })

        it('handles string numeric values from array', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: ['5', '15'],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBe(5)
            expect(logic.values.localMax).toBe(15)
        })

        it('handles NaN values', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: ['invalid', 'values'],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBeNull()
            expect(logic.values.localMax).toBeNull()
        })

        it('handles empty array values', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBeNull()
            expect(logic.values.localMax).toBeNull()
        })
    })

    describe('setLocalMin', () => {
        beforeEach(() => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()
        })

        it('updates local min and calls onSet with new array', () => {
            logic.actions.setLocalMin(15)
            expect(logic.values.localMin).toBe(15)
            expect(mockOnSet).toHaveBeenCalledWith([15, 20])
        })

        it('calls onSet with null when max is null', () => {
            logic.actions.setLocalMax(null)
            expect(mockOnSet).toHaveBeenCalledWith([10, NaN])
            mockOnSet.mockClear()

            logic.actions.setLocalMin(5)
            expect(mockOnSet).toHaveBeenCalledWith([5, NaN])
        })

        it('calls onSet with null when min is set to null', () => {
            logic.actions.setLocalMin(null)
            expect(logic.values.localMin).toBeNull()
            expect(mockOnSet).toHaveBeenCalledWith([NaN, 20])
        })

        it('calls onSet even when min is greater than max', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMin(25)
            expect(logic.values.localMin).toBe(25)
            expect(mockOnSet).toHaveBeenCalledWith([25, 20])
        })

        it('calls onSet when min equals max', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMin(20)
            expect(logic.values.localMin).toBe(20)
            expect(mockOnSet).toHaveBeenCalledWith([20, 20])
        })
    })

    describe('setLocalMax', () => {
        beforeEach(() => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()
        })

        it('updates local max and calls onSet with new array', () => {
            logic.actions.setLocalMax(25)
            expect(logic.values.localMax).toBe(25)
            expect(mockOnSet).toHaveBeenCalledWith([10, 25])
        })

        it('calls onSet with expected params', () => {
            logic.actions.setLocalMin(null)
            expect(mockOnSet).toHaveBeenCalledWith([NaN, 20])
            mockOnSet.mockClear()

            logic.actions.setLocalMax(30)
            expect(mockOnSet).toHaveBeenCalledWith([NaN, 30])
        })

        it('calls onSet when max is set to null', () => {
            logic.actions.setLocalMax(null)
            expect(logic.values.localMax).toBeNull()
            expect(mockOnSet).toHaveBeenCalledWith([10, NaN])
        })

        it('calls onSet even when max is less than min', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMax(5)
            expect(logic.values.localMax).toBe(5)
            expect(mockOnSet).toHaveBeenCalledWith([10, 5])
        })

        it('calls onSet when max equals min', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMax(10)
            expect(logic.values.localMax).toBe(10)
            expect(mockOnSet).toHaveBeenCalledWith([10, 10])
        })
    })

    describe('propsChanged cycle prevention', () => {
        it('calls onSet only once when setting local value', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()
            mockOnSet.mockClear()

            logic.actions.setLocalMin(15)

            expect(mockOnSet).toHaveBeenCalledTimes(1)
            expect(mockOnSet).toHaveBeenCalledWith([15, 20])
        })

        it('handles NaN values without infinite recursion', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()
            mockOnSet.mockClear()

            logic.actions.setLocalMin(null)
            expect(mockOnSet).toHaveBeenCalledWith([NaN, 20])
            expect(mockOnSet).toHaveBeenCalledTimes(1)

            mockOnSet.mockClear()
            logic.actions.setLocalMax(null)
            expect(mockOnSet).toHaveBeenCalledWith([NaN, NaN])
            expect(mockOnSet).toHaveBeenCalledTimes(1)
        })

        it('does not call setLocalMin/Max when props have same values', () => {
            const onSetSpy = jest.fn()

            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [10, 20],
                onSet: onSetSpy,
            })
            logic.mount()

            expect(logic.values.localMin).toBe(10)
            expect(logic.values.localMax).toBe(20)
            expect(onSetSpy).not.toHaveBeenCalled()
        })

        it('valuesMatch handles NaN correctly to prevent recursion', () => {
            logic = propertyFilterBetweenLogic({
                key: 'test-key',
                value: [NaN, 20],
                onSet: mockOnSet,
            })
            logic.mount()

            const firstCallCount = mockOnSet.mock.calls.length

            logic.actions.setLocalMin(null)

            expect(mockOnSet.mock.calls.length - firstCallCount).toBe(1)
        })
    })
})
