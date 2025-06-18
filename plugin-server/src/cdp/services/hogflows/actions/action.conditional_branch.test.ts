import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerConditionalBranch } from './action.conditional_branch'
import { findActionById, findActionByType } from './utils'

describe('HogFlowActionRunnerCondition', () => {
    let runner: HogFlowActionRunnerConditionalBranch
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'conditional_branch' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T00:00:00.000Z'))

        runner = new HogFlowActionRunnerConditionalBranch()

        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    conditional_branch: {
                        type: 'conditional_branch',
                        config: {
                            conditions: [
                                {
                                    filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters, // Match for pageviews
                                    on_match: 'condition_1',
                                },
                            ], // Filled by tests
                        },
                    },
                    condition_1: {
                        type: 'delay',
                        config: {
                            delay_duration: '2h',
                        },
                    },
                    condition_2: {
                        type: 'delay',
                        config: {
                            delay_duration: '2h',
                        },
                    },
                },
                edges: [
                    {
                        from: 'conditional_branch',
                        to: 'condition_2',
                        type: 'branch',
                        index: 1,
                    },
                    {
                        from: 'conditional_branch',
                        to: 'condition_1',
                        type: 'branch',
                        index: 0,
                    },
                ],
            })
            .build()

        action = findActionByType(hogFlow, 'conditional_branch')!
        invocation = createExampleHogFlowInvocation(hogFlow)

        invocation.state.currentAction = {
            id: action.id,
            startedAtTimestamp: DateTime.utc().toMillis(),
        }
    })

    describe('no matching events', () => {
        it('should return finished if no matches', () => {
            invocation.state.event!.event = 'no-match'
            const result = runner.run(invocation, action)
            expect(result).toEqual({
                done: true,
            })
        })

        describe('wait logic', () => {
            it('should handle wait duration and schedule next check', () => {
                action.config.delay_duration = '2h'
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
                done: true,
                goToAction: findActionById(invocation.hogFlow, 'condition_1'),
            })
        })

        it('should ignore conditions that do not match', () => {
            action.config.conditions = [
                {
                    filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // No match
                },
                {
                    filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters, // No match
                },
            ]

            const result = runner.run(invocation, action)
            expect(result).toEqual({
                done: true,
                goToAction: findActionById(invocation.hogFlow, 'condition_2'),
            })
        })
    })
})
