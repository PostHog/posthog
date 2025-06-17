import { DateTime } from 'luxon'

import { createExampleHogFlowInvocation, createHogFlowAction } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerDelay } from './delay.action'

describe('HogFlowActionRunnerDelay', () => {
    let runner: HogFlowActionRunnerDelay
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'delay' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T00:00:00.000Z'))

        runner = new HogFlowActionRunnerDelay()
        action = createHogFlowAction({
            type: 'delay',
            config: {
                delay_duration: '10m',
            },
        })
        invocation = createExampleHogFlowInvocation(
            {
                actions: [action],
            },
            {
                currentAction: {
                    id: action.id,
                    startedAtTimestamp: DateTime.utc().toMillis(),
                },
            }
        )
    })

    // NOTE: Most tests are covered in the common delay test file
    describe('delay step logic', () => {
        it('should handle wait duration and schedule next check', async () => {
            action.config.delay_duration = '10m'
            const result = await runner.run(invocation, action)
            expect(result).toEqual({
                finished: false,
                // Should schedule for 10 minutes from now
                scheduledAt: DateTime.utc().plus({ minutes: 10 }),
            })
        })

        it('should not schedule for later than the max wait duration', async () => {
            action.config.delay_duration = '5m'
            const result = await runner.run(invocation, action)
            expect(result).toEqual({
                finished: false,
                // Should schedule for 5 minutes from now
                scheduledAt: DateTime.utc().plus({ minutes: 5 }),
            })
        })

        it('should throw error if action started at timestamp is invalid', async () => {
            invocation.state.currentAction = undefined
            action.config.delay_duration = '300s'
            await expect(async () => await runner.run(invocation, action)).rejects.toThrow(
                "'startedAtTimestamp' is not set or is invalid"
            )
        })
    })
})
