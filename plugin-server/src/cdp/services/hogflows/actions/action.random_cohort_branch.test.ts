import { createExampleHogFlowInvocation, createHogFlowAction } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerRandomCohortBranch } from './action.random_cohort_branch'

describe('HogFlowActionRunnerRandomCohortBranch', () => {
    let runner: HogFlowActionRunnerRandomCohortBranch
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'random_cohort_branch' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.spyOn(Math, 'random')

        runner = new HogFlowActionRunnerRandomCohortBranch()
        action = createHogFlowAction({
            type: 'random_cohort_branch',
            config: {
                cohorts: [
                    { percentage: 30, on_match: 'cohort-a' },
                    { percentage: 40, on_match: 'cohort-b' },
                    { percentage: 30, on_match: 'cohort-c' },
                ],
            },
        })
        invocation = createExampleHogFlowInvocation(
            {
                actions: [action],
            },
            {
                currentAction: {
                    id: action.id,
                    startedAtTimestamp: Date.now(),
                },
            }
        )
    })

    it('should select first cohort when random is in first range', async () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.2) // 20% - in first cohort range
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'cohort-a',
        })
    })

    it('should select second cohort when random is in second range', async () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.4) // 40% - in second cohort range
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'cohort-b',
        })
    })

    it('should select third cohort when random is in third range', async () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.8) // 80% - in third cohort range
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'cohort-c',
        })
    })

    it('should handle edge cases at boundaries', async () => {
        ;(Math.random as jest.Mock).mockReturnValue(0.3) // Exactly at first boundary
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'cohort-a',
        })
        ;(Math.random as jest.Mock).mockReturnValue(0.7) // Exactly at second boundary
        const result2 = await runner.run(invocation, action)
        expect(result2).toEqual({
            finished: true,
            goToActionId: 'cohort-b',
        })
    })

    it('should handle single cohort', async () => {
        action.config.cohorts = [{ percentage: 100, on_match: 'single-cohort' }]
        ;(Math.random as jest.Mock).mockReturnValue(0.5)
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'single-cohort',
        })
    })

    it('should handle uneven percentages', async () => {
        action.config.cohorts = [
            { percentage: 25, on_match: 'cohort-a' },
            { percentage: 75, on_match: 'cohort-b' },
        ]
        ;(Math.random as jest.Mock).mockReturnValue(0.5) // 50% - in second cohort range
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'cohort-b',
        })
    })

    it('should fallback to last cohort if percentages dont add up to 100', async () => {
        action.config.cohorts = [
            { percentage: 30, on_match: 'cohort-a' },
            { percentage: 30, on_match: 'cohort-b' },
        ]
        ;(Math.random as jest.Mock).mockReturnValue(0.9) // 90% - beyond all defined ranges
        const result = await runner.run(invocation, action)
        expect(result).toEqual({
            finished: true,
            goToActionId: 'cohort-b',
        })
    })
})
