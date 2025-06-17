import { DateTime } from 'luxon'

import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation, createHogFlowAction } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerWaitForCondition } from './action.wait_for_condition'

describe('HogFlowActionRunnerWaitForCondition', () => {
    let runner: HogFlowActionRunnerWaitForCondition
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'wait_until_condition' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T00:00:00.000Z'))

        runner = new HogFlowActionRunnerWaitForCondition()
        action = createHogFlowAction({
            type: 'wait_until_condition',
            config: {
                condition: {
                    filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                    on_match: 'next-action',
                },
                max_wait_duration: '10m',
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

    describe('no matching events', () => {
        it('should handle wait duration and schedule next check', () => {
            action.config.max_wait_duration = '2h'
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                finished: false,
                // Should schedule for 10 minutes from now
                scheduledAt: DateTime.utc().plus({ minutes: 10 }),
            })
        })

        it('should not schedule for later than the max wait duration', () => {
            action.config.max_wait_duration = '5m'
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                finished: false,
                // Should schedule for 5 minutes from now
                scheduledAt: DateTime.utc().plus({ minutes: 5 }),
            })
        })

        it('should throw error if action started at timestamp is invalid', () => {
            invocation.state.currentAction = undefined
            action.config.max_wait_duration = '300s'
            expect(() => runner.run(invocation, action)).toThrow("'startedAtTimestamp' is not set or is invalid")
        })
    })

    describe('matching events', () => {
        beforeEach(() => {
            // These values match the pageview_or_autocapture_filter
            invocation.state.event!.event = '$pageview'
            invocation.state.event!.properties = {
                $current_url: 'https://posthog.com',
            }
        })

        it('should match condition and go to action', () => {
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                finished: true,
                goToActionId: 'next-action',
            })
        })

        it('should ignore conditions that do not match', () => {
            action.config.condition.filter = HOG_FILTERS_EXAMPLES.elements_text_filter.filters // No match
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                finished: false,
                scheduledAt: DateTime.utc().plus({ minutes: 10 }),
            })
        })
    })
})
