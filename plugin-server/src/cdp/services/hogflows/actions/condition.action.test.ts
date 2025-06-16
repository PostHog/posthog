import { DateTime } from 'luxon'

import { HOG_FILTERS_EXAMPLES } from '~/src/cdp/_tests/examples'
import { createExampleHogFlowInvocation, createHogFlowAction } from '~/src/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/src/cdp/types'
import { HogFlowAction } from '~/src/schema/hogflow'

import { HogFlowActionRunnerCondition } from './condition.action'

describe('HogFlowActionRunnerCondition', () => {
    let runner: HogFlowActionRunnerCondition
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'conditional_branch' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T00:00:00.000Z'))

        runner = new HogFlowActionRunnerCondition()
        action = createHogFlowAction('conditional_branch', {
            conditions: [
                {
                    filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                    on_match: 'next-action',
                },
            ],
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
        it('should return finished if no matches', async () => {
            invocation.state.event!.event = 'no-match'
            const result = await runner.run(invocation, action)
            expect(result).toEqual({
                finished: true,
            })
        })

        describe('wait logic', () => {
            it('should handle wait duration and schedule next check', async () => {
                action.config.wait_duration_seconds = 60 * 60 * 2 // 2 hours
                const result = await runner.run(invocation, action)
                expect(result).toEqual({
                    finished: false,
                    // Should schedule for 10 minutes from now
                    scheduledAt: DateTime.utc().plus({ minutes: 10 }),
                })
            })

            it('should not schedule for later than the max wait duration', async () => {
                action.config.wait_duration_seconds = 60 * 5 // 5 minutes
                const result = await runner.run(invocation, action)
                expect(result).toEqual({
                    finished: false,
                    // Should schedule for 5 minutes from now
                    scheduledAt: DateTime.utc().plus({ minutes: 5 }),
                })
            })

            it('should throw error if action started at timestamp is invalid', async () => {
                invocation.state.currentAction = undefined
                action.config.wait_duration_seconds = 300
                await expect(async () => await runner.run(invocation, action)).rejects.toThrow(
                    "'currentAction.startedAtTimestamp' is not set or is invalid"
                )
            })
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

        it('should match condition and go to action', async () => {
            const result = await runner.run(invocation, action)
            expect(result).toEqual({
                finished: true,
                goToActionId: 'next-action',
            })
        })

        it('should ignore conditions that do not match', async () => {
            action.config.conditions = [
                {
                    filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // No match
                    on_match: 'action-1',
                },
                {
                    filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // No match
                    on_match: 'action-2',
                },
                {
                    filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters, // Match
                    on_match: 'action-3',
                },
            ]
            const result = await runner.run(invocation, action)
            expect(result).toEqual({
                finished: true,
                goToActionId: 'action-3',
            })
        })
    })
})
