import { DateTime } from 'luxon'

import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation, createHogFlowAction } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'
import { Hub } from '~/types'

import { HogFlowActionRunner } from './hogflow-action-runner'
import { HogFlowActionRunnerResult } from './types'

describe('HogFlowActionRunner', () => {
    let runner: HogFlowActionRunner
    let invocation: CyclotronJobInvocationHogFlow
    let action: HogFlowAction

    beforeEach(() => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        const mockHub = {} as Hub

        runner = new HogFlowActionRunner(mockHub)
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

    const commonActions: Record<string, HogFlowAction> = {
        trigger: createHogFlowAction({
            type: 'trigger',
            config: {
                filters: HOG_FILTERS_EXAMPLES.no_filters.filters,
            },
        }),
        delay: createHogFlowAction({
            type: 'delay',
            config: {
                delay_duration: '2h',
            },
        }),
        exit: createHogFlowAction({
            type: 'exit',
            config: {},
        }),
    }

    describe('per action runner tests', () => {
        // NOTE: We test one case of each action to ensure it works as expected, the rest is handles as per-action unit test

        beforeEach(() => {
            // Conditions that match the "pageview_or_autocapture_filter"
            invocation.state.event.event = '$pageview'
            invocation.state.event.properties = {
                $current_url: 'https://posthog.com',
            }

            // For the random_cohort_branch action
            jest.spyOn(Math, 'random').mockReturnValue(0.8)
        })

        const cases: [string, HogFlowAction, Partial<HogFlowActionRunnerResult>][] = [
            [
                'wait_until_condition',
                createHogFlowAction({
                    type: 'wait_until_condition',
                    config: {
                        condition: {
                            filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // no match
                            on_match: 'next-action',
                        },
                        max_wait_duration: '10m',
                    },
                }),
                {
                    finished: false,
                    scheduledAt: DateTime.fromISO('2025-01-01T00:10:00.000Z').toUTC(),
                },
            ],
            [
                'conditional_branch',
                createHogFlowAction({
                    type: 'conditional_branch',
                    config: {
                        conditions: [
                            {
                                filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters,
                                on_match: commonActions.trigger.id,
                            },
                            {
                                filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                                on_match: commonActions.delay.id, // TODO: Change these to be edges...
                            },
                        ],
                    },
                }),
                {
                    finished: true,
                    goToAction: commonActions.delay,
                },
            ],
            [
                'delay',
                createHogFlowAction({
                    type: 'delay',
                    config: {
                        delay_duration: '2h',
                    },
                }),
                {
                    finished: false,
                    scheduledAt: DateTime.fromISO('2025-01-01T02:00:00.000Z').toUTC(),
                },
            ],
            [
                'random_cohort_branch',
                createHogFlowAction({
                    type: 'random_cohort_branch',
                    config: {
                        cohorts: [
                            { percentage: 50, on_match: commonActions.trigger.id },
                            { percentage: 50, on_match: commonActions.delay.id },
                        ],
                    },
                }),
                {
                    finished: true,
                    goToAction: commonActions.delay,
                },
            ],
            [
                'exit',
                createHogFlowAction({
                    type: 'exit',
                    config: {},
                }),
                { finished: true },
            ],
        ]

        it.each(cases)('should run %s action', async (_actionType, action, expectation) => {
            // NOTE: Test case to be used for generically trying a bunch of actions and outcomes
            invocation.hogFlow.actions = [commonActions.trigger, commonActions.delay, action]
            invocation.state.currentAction = {
                id: action.id,
                startedAtTimestamp: DateTime.utc().toMillis(),
            }

            const result = await runner.runCurrentAction(invocation)
            expect(result).toEqual({
                action,
                ...expectation,
            })
        })
    })

    describe('action filtering', () => {
        let action: HogFlowAction
        beforeEach(() => {
            // Conditions that match the "pageview_or_autocapture_filter"
            invocation.state.event.event = '$pageview'
            invocation.state.event.properties = {
                $current_url: 'https://posthog.com',
            }

            action = createHogFlowAction({
                type: 'delay',
                config: {
                    delay_duration: '2h',
                },
                filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
            })

            invocation.hogFlow.actions = [commonActions.trigger, commonActions.delay, action]
            invocation.state.currentAction = {
                id: action.id,
                startedAtTimestamp: DateTime.utc().toMillis(),
            }
        })

        it("should not skip the action if the filters don't match", async () => {
            invocation.state.event.event = 'not-a-pageview'
            const result = await runner.runCurrentAction(invocation)
            expect(result).toEqual({
                action,
                finished: false,
                scheduledAt: DateTime.fromISO('2025-01-01T02:00:00.000Z').toUTC(),
            })
        })

        it('should skip the action if the filters do match', async () => {
            invocation.state.event.event = '$pageview'
            const result = await runner.runCurrentAction(invocation)
            expect(result).toEqual({
                action,
                finished: true,
            })
        })
    })
})
