import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { findActionById, findActionByType } from '../hogflow-utils'
import { getRandomCohort } from './random_cohort_branch'

describe('getRandomCohort', () => {
    let action: Extract<HogFlowAction, { type: 'random_cohort_branch' }>
    let invocation: CyclotronJobInvocationHogFlow

    beforeEach(() => {
        jest.useFakeTimers()
        jest.spyOn(Math, 'random')

        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    random_cohort_branch: {
                        type: 'random_cohort_branch',
                        config: {
                            cohorts: [{ percentage: 30 }, { percentage: 40 }, { percentage: 30 }],
                        },
                    },
                    cohort_a: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                    cohort_b: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                    cohort_c: {
                        type: 'delay',
                        config: { delay_duration: '2h' },
                    },
                },
                edges: [
                    {
                        from: 'random_cohort_branch',
                        to: 'cohort_a',
                        type: 'branch',
                        index: 0,
                    },
                    {
                        from: 'random_cohort_branch',
                        to: 'cohort_b',
                        type: 'branch',
                        index: 1,
                    },
                    {
                        from: 'random_cohort_branch',
                        to: 'cohort_c',
                        type: 'branch',
                        index: 2,
                    },
                ],
            })
            .build()

        action = findActionByType(hogFlow, 'random_cohort_branch')!
        invocation = createExampleHogFlowInvocation(hogFlow)
    })

    it('should select first cohort when random is in first range', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.2) // 20% - in first cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_a'))
    })

    it('should select second cohort when random is in second range', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.4) // 40% - in second cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })

    it('should select third cohort when random is in third range', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.8) // 80% - in third cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_c'))
    })

    it('should handle edge cases at boundaries', () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.3) // Exactly at first boundary
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_a'))
        ;(Math.random as jest.Mock).mockReturnValue(0.7) // Exactly at second boundary
        const result2 = getRandomCohort(invocation, action)
        expect(result2).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })

    it('should handle single cohort', () => {
        action.config.cohorts = [{ percentage: 100 }]
        ;(Math.random as jest.Mock).mockReturnValue(0.9)
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_a'))
    })

    it('should handle uneven percentages', () => {
        action.config.cohorts = [{ percentage: 25 }, { percentage: 75 }]
        ;(Math.random as jest.Mock).mockReturnValue(0.5) // 50% - in second cohort range
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })

    it('should fallback to last cohort if percentages dont add up to 100', () => {
        action.config.cohorts = [{ percentage: 30 }, { percentage: 30 }]
        ;(Math.random as jest.Mock).mockReturnValue(0.9) // 90% - beyond all defined ranges
        const result = getRandomCohort(invocation, action)
        expect(result).toEqual(findActionById(invocation.hogFlow, 'cohort_b'))
    })
})
