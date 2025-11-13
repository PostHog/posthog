import { expectLogic } from 'kea-test-utils'

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
        it('initializes with undefined values when value is null', () => {
            logic = propertyFilterBetweenLogic({
                value: null,
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBeNull()
            expect(logic.values.localMax).toBeNull()
            expect(logic.values.errorMessage).toBeNull()
        })

        it('initializes with numeric values from array', () => {
            logic = propertyFilterBetweenLogic({
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBe(10)
            expect(logic.values.localMax).toBe(20)
            expect(logic.values.errorMessage).toBeNull()
        })

        it('handles string numeric values from array', () => {
            logic = propertyFilterBetweenLogic({
                value: ['5', '15'],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBe(5)
            expect(logic.values.localMax).toBe(15)
            expect(logic.values.errorMessage).toBeNull()
        })

        it('handles NaN values', () => {
            logic = propertyFilterBetweenLogic({
                value: ['invalid', 'values'],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBeNull()
            expect(logic.values.localMax).toBeNull()
        })

        it('handles empty array values', () => {
            logic = propertyFilterBetweenLogic({
                value: [],
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.localMin).toBeNull()
            expect(logic.values.localMax).toBeNull()
        })
    })

    describe('error message', () => {
        it('shows error when min is greater than max', async () => {
            logic = propertyFilterBetweenLogic({
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setLocalMin(30)
            }).toMatchValues({
                errorMessage: 'Min must be less than or equal to max',
            })
        })

        it('shows no error when min equals max', async () => {
            logic = propertyFilterBetweenLogic({
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setLocalMin(20)
            }).toMatchValues({
                errorMessage: null,
            })
        })

        it('shows no error when min is less than max', async () => {
            logic = propertyFilterBetweenLogic({
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setLocalMin(15)
            }).toMatchValues({
                errorMessage: null,
            })
        })

        it('shows no error when either value is undefined initially', async () => {
            logic = propertyFilterBetweenLogic({
                value: null,
                onSet: mockOnSet,
            })
            logic.mount()

            expect(logic.values.errorMessage).toBeNull()
        })

        it('shows error after setting min when max is undefined', async () => {
            logic = propertyFilterBetweenLogic({
                value: null,
                onSet: mockOnSet,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setLocalMin(10)
                logic.actions.setLocalMax(5)
            }).toMatchValues({
                errorMessage: 'Min must be less than or equal to max',
            })
        })
    })

    describe('setLocalMin', () => {
        beforeEach(() => {
            logic = propertyFilterBetweenLogic({
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()
        })

        it('calls onSet with new array when valid', () => {
            logic.actions.setLocalMin(15)
            expect(mockOnSet).toHaveBeenCalledWith([15, 20])
        })

        it('calls onSet with null when max is set to null', () => {
            logic.actions.setLocalMax(null)
            expect(mockOnSet).toHaveBeenCalledWith(null)
            mockOnSet.mockClear()

            logic.actions.setLocalMin(5)
            expect(mockOnSet).toHaveBeenCalledWith(null)
        })

        it('calls onSet with null when value is null', () => {
            logic.actions.setLocalMin(null)
            expect(mockOnSet).toHaveBeenCalledWith(null)
        })

        it('does not call onSet when min is greater than max', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMin(25)
            expect(mockOnSet).not.toHaveBeenCalled()
        })

        it('calls onSet when min equals max', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMin(20)
            expect(mockOnSet).toHaveBeenCalledWith([20, 20])
        })
    })

    describe('setLocalMax', () => {
        beforeEach(() => {
            logic = propertyFilterBetweenLogic({
                value: [10, 20],
                onSet: mockOnSet,
            })
            logic.mount()
        })

        it('calls onSet with new array when valid', () => {
            logic.actions.setLocalMax(25)
            expect(mockOnSet).toHaveBeenCalledWith([10, 25])
        })

        it('calls onSet with null when min is set to null', () => {
            logic.actions.setLocalMin(null)
            expect(mockOnSet).toHaveBeenCalledWith(null)
            mockOnSet.mockClear()

            logic.actions.setLocalMax(30)
            expect(mockOnSet).toHaveBeenCalledWith(null)
        })

        it('calls onSet with null when value is null', () => {
            logic.actions.setLocalMax(null)
            expect(mockOnSet).toHaveBeenCalledWith(null)
        })

        it('does not call onSet when max is less than min', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMax(5)
            expect(mockOnSet).not.toHaveBeenCalled()
        })

        it('calls onSet when max equals min', () => {
            mockOnSet.mockClear()
            logic.actions.setLocalMax(10)
            expect(mockOnSet).toHaveBeenCalledWith([10, 10])
        })
    })
})
