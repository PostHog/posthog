import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlow } from '~/schema/hogflow'
import { Hub } from '~/types'

import { HogFlowActionRunner } from './hogflow-action-runner'
import { HogFlowActionRunnerResult } from './types'

describe('HogFlowActionRunner', () => {
    let runner: HogFlowActionRunner

    beforeEach(() => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        const mockHub = {} as Hub
        runner = new HogFlowActionRunner(mockHub)
    })

    const createHogInvocation = (
        flow: SimpleHogFlowRepresentation
    ): { hogFlow: HogFlow; invocation: CyclotronJobInvocationHogFlow } => {
        const hogFlow = new FixtureHogFlowBuilder()
            .withExitCondition('exit_on_conversion')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: {
                            filters: HOG_FILTERS_EXAMPLES.no_filters.filters,
                        },
                    },
                    delay: {
                        type: 'delay',
                        config: {
                            delay_duration: '2h',
                        },
                    },
                    exit: {
                        type: 'exit',
                        config: {},
                    },
                    ...flow.actions,
                },
                edges: flow.edges,
            })
            .build()

        const invocation = createExampleHogFlowInvocation(hogFlow, {
            currentAction: {
                id: hogFlow.actions[0].id,
                startedAtTimestamp: DateTime.utc().toMillis(),
            },
        })

        return { hogFlow, invocation }
    }

    describe('per action runner tests', () => {
        // NOTE: We test one case of each action to ensure it works as expected, the rest is handles as per-action unit test
        const cases: [
            string,
            SimpleHogFlowRepresentation,
            Partial<Omit<HogFlowActionRunnerResult, 'goToAction'> & { goToActionId: string }>
        ][] = [
            [
                'wait_until_condition',
                {
                    actions: {
                        wait_until_condition: {
                            type: 'wait_until_condition',
                            config: {
                                condition: {
                                    filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // no match
                                    on_match: 'next-action',
                                },
                                max_wait_duration: '10m',
                            },
                        },
                    },
                    edges: [
                        {
                            from: 'trigger',
                            to: 'wait_until_condition',
                            type: 'continue',
                        },
                    ],
                },
                {
                    finished: false,
                    scheduledAt: DateTime.fromISO('2025-01-01T00:10:00.000Z').toUTC(),
                },
            ],

            [
                'conditional_branch',
                {
                    actions: {
                        conditional_branch: {
                            type: 'conditional_branch',
                            config: {
                                conditions: [
                                    {
                                        filter: HOG_FILTERS_EXAMPLES.elements_text_filter.filters,
                                    },
                                    {
                                        filter: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                                    },
                                ],
                            },
                        },
                    },
                    edges: [
                        {
                            from: 'conditional_branch',
                            to: 'exit',
                            type: 'branch',
                            index: 0,
                        },
                        {
                            from: 'conditional_branch',
                            to: 'delay',
                            type: 'branch',
                            index: 1,
                        },
                    ],
                },

                {
                    finished: true,
                    goToActionId: 'delay',
                },
            ],
            [
                'delay',
                {
                    actions: {
                        delay: {
                            type: 'delay',
                            config: {
                                delay_duration: '2h',
                            },
                        },
                    },
                    edges: [
                        {
                            from: 'delay',
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                },
                {
                    finished: false,
                    scheduledAt: DateTime.fromISO('2025-01-01T02:00:00.000Z').toUTC(),
                },
            ],
            [
                'random_cohort_branch',
                {
                    actions: {
                        random_cohort_branch: {
                            type: 'random_cohort_branch',
                            config: {
                                cohorts: [
                                    {
                                        percentage: 50,
                                    },
                                    {
                                        percentage: 50,
                                    },
                                ],
                            },
                        },
                    },
                    edges: [
                        {
                            from: 'random_cohort_branch',
                            to: 'exit',
                            type: 'branch',
                            index: 0,
                        },
                        {
                            from: 'random_cohort_branch',
                            to: 'delay',
                            type: 'branch',
                            index: 1,
                        },
                    ],
                },
                {
                    finished: true,
                    goToActionId: 'delay',
                },
            ],
            [
                'exit',
                {
                    actions: {
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [
                        {
                            from: 'exit',
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                },
                { finished: true },
            ],
        ]

        it.each(cases)('should run %s action', async (actionId, workflow, { goToActionId, ...expectation }) => {
            const { invocation } = createHogInvocation(workflow)

            // Conditions that match the "pageview_or_autocapture_filter"
            invocation.state.event.event = '$pageview'
            invocation.state.event.properties = {
                $current_url: 'https://posthog.com',
            }

            // For the random_cohort_branch action
            jest.spyOn(Math, 'random').mockReturnValue(0.8)

            invocation.state.currentAction = {
                id: actionId,
                startedAtTimestamp: DateTime.utc().toMillis(),
            }

            const result = await runner.runCurrentAction(invocation)
            expect(result).toEqual({
                action: invocation.hogFlow.actions.find((action) => action.id === actionId),
                ...expectation,
                goToAction: goToActionId ? runner.findActionById(invocation, goToActionId) : undefined,
            })
        })
    })

    // describe('action filtering', () => {
    //     let action: HogFlowAction
    //     beforeEach(() => {
    //         // Conditions that match the "pageview_or_autocapture_filter"
    //         invocation.state.event.event = '$pageview'
    //         invocation.state.event.properties = {
    //             $current_url: 'https://posthog.com',
    //         }

    //         action = createHogFlowAction({
    //             type: 'delay',
    //             config: {
    //                 delay_duration: '2h',
    //             },
    //             filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
    //         })

    //         invocation.hogFlow.actions = [commonActions.trigger, commonActions.delay, action]
    //         invocation.state.currentAction = {
    //             id: action.id,
    //             startedAtTimestamp: DateTime.utc().toMillis(),
    //         }
    //     })

    //     it("should not skip the action if the filters don't match", async () => {
    //         invocation.state.event.event = 'not-a-pageview'
    //         const result = await runner.runCurrentAction(invocation)
    //         expect(result).toEqual({
    //             action,
    //             finished: false,
    //             scheduledAt: DateTime.fromISO('2025-01-01T02:00:00.000Z').toUTC(),
    //         })
    //     })

    //     it('should skip the action if the filters do match', async () => {
    //         invocation.state.event.event = '$pageview'
    //         const result = await runner.runCurrentAction(invocation)
    //         expect(result).toEqual({
    //             action,
    //             finished: true,
    //         })
    //     })
    // })
})
