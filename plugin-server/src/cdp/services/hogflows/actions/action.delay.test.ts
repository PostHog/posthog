import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerDelay } from './action.delay'
import { findActionByType } from './utils'

describe('HogFlowActionRunnerDelay', () => {
    let runner: HogFlowActionRunnerDelay
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'delay' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T00:00:00.000Z'))

        runner = new HogFlowActionRunnerDelay()

        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    delay: {
                        type: 'delay',
                        config: {
                            delay_duration: '10m',
                        },
                    },
                },
                edges: [],
            })
            .build()

        action = findActionByType(hogFlow, 'delay')!
        invocation = createExampleHogFlowInvocation(hogFlow, {
            currentAction: {
                id: action.id,
                startedAtTimestamp: DateTime.utc().toMillis(),
            },
        })
    })

    // NOTE: Most tests are covered in the common delay test file
    describe('delay step logic', () => {
        it('should handle wait duration and schedule next check', () => {
            action.config.delay_duration = '10m'
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                done: false,
                // Should schedule for 10 minutes from now
                scheduledAt: DateTime.utc().plus({ minutes: 10 }),
            })
        })

        it('should not schedule for later than the max wait duration', () => {
            action.config.delay_duration = '5m'
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                done: false,
                // Should schedule for 5 minutes from now
                scheduledAt: DateTime.utc().plus({ minutes: 5 }),
            })
        })

        it('should throw error if action started at timestamp is invalid', () => {
            invocation.state.currentAction = undefined
            action.config.delay_duration = '300s'
            expect(() => runner.run(invocation, action)).toThrow("'startedAtTimestamp' is not set or is invalid")
        })
    })
})
