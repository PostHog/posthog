import { ProductTourStep, StepOrderVersion } from '~/types'

import { getStepsForVersion, getUpdatedStepOrderHistory, normalizeStepOrderHistory } from './stepUtils'

describe('stepUtils step order history', () => {
    const step = (id: string): ProductTourStep => ({ id, type: 'modal', content: null })

    it.each([
        [
            'a version missing its steps snapshot',
            { id: 'v1', created_at: '2026-08-30T00:00:00.000Z' } as StepOrderVersion,
        ],
        ['a null version', null],
    ])('getStepsForVersion falls back to the current steps for %s instead of throwing', (_label, version) => {
        expect(getStepsForVersion([step('a'), step('b')], version).map((s) => s.id)).toEqual(['a', 'b'])
    })

    it('getStepsForVersion returns the version snapshot when it is present', () => {
        const version: StepOrderVersion = {
            id: 'v1',
            steps: [step('b'), step('a')],
            created_at: '2026-08-30T00:00:00.000Z',
        }

        expect(getStepsForVersion([step('a'), step('b')], version).map((s) => s.id)).toEqual(['b', 'a'])
    })

    it('treats a version missing its steps snapshot as changed instead of throwing', () => {
        const brokenHistory = [{ id: 'v1', created_at: '2026-08-30T00:00:00.000Z' } as StepOrderVersion]

        const result = getUpdatedStepOrderHistory([step('a')], brokenHistory)

        expect(result).toHaveLength(2)
        expect(result[1].steps.map((s) => s.id)).toEqual(['a'])
    })

    it('does not append a version when the step order is unchanged', () => {
        const history: StepOrderVersion[] = [{ id: 'v1', steps: [step('a')], created_at: '2026-08-30T00:00:00.000Z' }]

        expect(getUpdatedStepOrderHistory([step('a')], history)).toHaveLength(1)
    })

    it('drops broken history entries on normalize so a stored tour heals itself', () => {
        const history = [
            { id: 'v1', created_at: '2026-08-30T00:00:00.000Z' } as StepOrderVersion,
            { id: 'v2', steps: [step('a')], created_at: '2026-08-30T00:00:01.000Z' },
        ]

        expect(normalizeStepOrderHistory(history)).toEqual([history[1]])
        expect(normalizeStepOrderHistory(undefined)).toBeUndefined()
    })
})
