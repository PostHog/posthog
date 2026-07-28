import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'

import { findActionById, findActionByType } from '../hogflow-utils'
import {
    ConditionalBranchHandler,
    checkConditions,
    counterHogflowRekeyWake,
    counterHogflowWaitPollOnlyAdvance,
} from './conditional_branch'

const pollOnlyAdvanceCount = async (): Promise<number> =>
    (await counterHogflowWaitPollOnlyAdvance.get()).values[0]?.value ?? 0

const pollOnlyAdvanceLabels = async (): Promise<Record<string, string | number> | undefined> =>
    (await counterHogflowWaitPollOnlyAdvance.get()).values[0]?.labels

const rekeyWakeCount = async (outcome: 'advanced' | 'reparked'): Promise<number> =>
    (await counterHogflowRekeyWake.get()).values.find((v) => v.labels.outcome === outcome)?.value ?? 0

describe('action.conditional_branch', () => {
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'conditional_branch' }>
    let hogFlow: HogFlow

    beforeEach(() => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    conditional_branch: {
                        type: 'conditional_branch',
                        config: {
                            conditions: [
                                {
                                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters, // Match for pageviews
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
        it('should return finished if no matches', async () => {
            invocation.state.event!.event = 'no-match'
            const result = await checkConditions(invocation, action)
            expect(result).toEqual({})
        })

        describe('wait logic', () => {
            it('should handle wait duration and schedule next check', async () => {
                action.config.delay_duration = '2h'
                const result = await checkConditions(invocation, action)
                expect(result).toEqual({
                    // Should schedule for 10 minutes from now
                    scheduledAt: DateTime.utc().plus({ minutes: 10 }),
                })
            })

            it('should not schedule for later than the max wait duration', async () => {
                action.config.delay_duration = '5m'
                const result = await checkConditions(invocation, action)
                expect(result).toEqual({
                    // Should schedule for 5 minutes from now
                    scheduledAt: DateTime.utc().plus({ minutes: 5 }),
                })
            })

            it('should throw error if action started at timestamp is invalid', async () => {
                invocation.state.currentAction = undefined
                action.config.delay_duration = '300s'
                await expect(async () => checkConditions(invocation, action)).rejects.toThrow(
                    "'startedAtTimestamp' is not set or is invalid"
                )
            })
        })
    })

    describe('matching events', () => {
        beforeEach(() => {
            invocation = createExampleHogFlowInvocation(hogFlow, {
                // These values match the pageview_or_autocapture_filter
                event: {
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                    },
                } as any,
            })
        })

        it('should match condition and go to action', async () => {
            const result = await checkConditions(invocation, action)
            expect(result).toEqual({
                nextAction: findActionById(invocation.hogFlow, 'condition_1'),
            })
        })

        it('should ignore conditions that do not match', async () => {
            action.config.conditions = [
                {
                    filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // No match
                },
                {
                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters, // No match
                },
            ]

            const result = await checkConditions(invocation, action)
            expect(result).toEqual({
                nextAction: findActionById(invocation.hogFlow, 'condition_2'),
            })
        })

        it('should execute the first matching branch when multiple conditions match', async () => {
            action.config.conditions = [
                {
                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters, // Match
                },
                {
                    filters: HOG_FILTERS_EXAMPLES.no_filters.filters, // Also matches (always true)
                },
            ]

            const result = await checkConditions(invocation, action)
            expect(result).toEqual({
                nextAction: findActionById(invocation.hogFlow, 'condition_1'),
            })
        })
    })

    describe('wait_until_condition eventMatched short-circuit', () => {
        let waitInvocation: CyclotronJobInvocationHogFlow
        let waitAction: Extract<HogFlowAction, { type: 'wait_until_condition' }>
        let handler: ConditionalBranchHandler

        beforeEach(() => {
            const waitFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        wait_until_condition: {
                            type: 'wait_until_condition',
                            config: {
                                condition: {
                                    filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // no match
                                },
                                max_wait_duration: '10m',
                            },
                        },
                        matched_target: {
                            type: 'delay',
                            config: { delay_duration: '2h' },
                        },
                    },
                    edges: [
                        {
                            from: 'wait_until_condition',
                            to: 'matched_target',
                            type: 'branch',
                            index: 0,
                        },
                    ],
                })
                .build()

            waitAction = findActionByType(waitFlow, 'wait_until_condition')!
            waitInvocation = createExampleHogFlowInvocation(waitFlow)
            waitInvocation.state.currentAction = {
                id: waitAction.id,
                startedAtTimestamp: DateTime.utc().toMillis(),
            }
            handler = new ConditionalBranchHandler()
            counterHogflowWaitPollOnlyAdvance.reset()
            counterHogflowRekeyWake.reset()
        })

        it('advances to the matched branch and clears eventMatched', async () => {
            waitInvocation.state.currentAction!.eventMatched = true
            waitInvocation.state.currentAction!.eventMatchedEvent = 'subscription created'
            waitInvocation.state.currentAction!.eventMatchedEventUuid = 'evt-uuid'

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.nextAction).toEqual(findActionById(waitInvocation.hogFlow, 'matched_target'))
            expect(result.result).toEqual({ eventMatched: true })
            // All wake markers are cleared so a later timeout fire isn't misread as an event wake.
            expect(waitInvocation.state.currentAction!.eventMatched).toBe(false)
            expect(waitInvocation.state.currentAction!.eventMatchedEvent).toBeUndefined()
            expect(waitInvocation.state.currentAction!.eventMatchedEventUuid).toBeUndefined()
        })

        it('falls through to condition evaluation when eventMatched is not set', async () => {
            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            // Condition does not match, so the step reschedules itself rather than advancing.
            expect(result.scheduledAt).toBeDefined()
            expect(result.nextAction).toBeUndefined()
        })

        it('does not fire immediately when the condition has no properties (always-true bytecode)', async () => {
            // An empty property condition compiles to always-true bytecode. It must not match on
            // entry and advance the wait; the step should park until an event wakes it or it times out.
            waitAction.config.condition = { filters: HOG_FILTERS_EXAMPLES.no_filters.filters }

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.scheduledAt).toBeDefined()
            expect(result.nextAction).toBeUndefined()
        })

        it('re-parks a wait_until_condition on the 10-minute cap (polling retained as backstop)', async () => {
            // Polling is kept for now: a wait_until_condition re-parks on the 10-minute cap and
            // re-checks its condition, even though the subscription matcher also wakes it early on a
            // matching signal. A 30-minute wait therefore schedules ~10 minutes out, not ~30.
            waitAction.config.max_wait_duration = '30m'

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.scheduledAt).toEqual(DateTime.utc().plus({ minutes: 10 }))
        })

        describe('wake plan scheduling', () => {
            // Reads person.properties.due_at and returns it as a unix timestamp, mirroring the shape
            // the save-time analyzer emits for `now() >= <person date>`.
            const dueAtTimer = ['_H', 1, 32, 'due_at', 32, 'properties', 32, 'person', 1, 3, 2, 'toUnixTimestamp', 1]

            it('parks to the timer instant instead of the polling cap', async () => {
                // The whole point of the wake plan: a clock-based wait sleeps once, to the moment its
                // condition flips, rather than waking every 10 minutes to ask. Regression this catches
                // is the cap winning over a resolvable timer, which silently restores polling.
                waitAction.config.max_wait_duration = '30d'
                waitAction.config.wake_plan = { streams: ['person'], timers: [dueAtTimer] }
                waitInvocation.person = {
                    properties: { due_at: DateTime.utc().plus({ days: 6 }).toISO() },
                } as any

                const result = await handler.execute({
                    invocation: waitInvocation,
                    action: waitAction,
                    result: createInvocationResult(waitInvocation),
                })

                expect(result.scheduledAt!.toISO()).toEqual(DateTime.utc().plus({ days: 6 }).toISO())
            })

            it('never sleeps past the step deadline even when the timer is later', async () => {
                // A timer beyond max_wait must not extend the wait: the deadline is a hard ceiling, and
                // overshooting it would strand the run instead of letting it take the timeout branch.
                waitAction.config.max_wait_duration = '1h'
                waitAction.config.wake_plan = { streams: ['person'], timers: [dueAtTimer] }
                waitInvocation.person = {
                    properties: { due_at: DateTime.utc().plus({ days: 6 }).toISO() },
                } as any

                const result = await handler.execute({
                    invocation: waitInvocation,
                    action: waitAction,
                    result: createInvocationResult(waitInvocation),
                })

                expect(result.scheduledAt).toEqual(DateTime.utc().plus({ hours: 1 }))
            })

            it('retries shortly when a timer cannot resolve yet', async () => {
                // The production flow writes the date it waits on in the preceding step, and that write
                // lands via ingestion — so the timer is unresolvable on first park. It must retry soon,
                // never sleep to the deadline, or the wake is lost for the whole max_wait.
                waitAction.config.max_wait_duration = '30d'
                waitAction.config.wake_plan = { streams: ['person'], timers: [dueAtTimer] }
                waitInvocation.person = { properties: {} } as any

                const result = await handler.execute({
                    invocation: waitInvocation,
                    action: waitAction,
                    result: createInvocationResult(waitInvocation),
                })

                expect(result.scheduledAt).toEqual(DateTime.utc().plus({ minutes: 5 }))
            })

            it('parks to the deadline when the condition has no clock dependence', async () => {
                // Analyzed and clock-free: only a message can satisfy it, and the matcher delivers
                // those, so there is nothing for a re-check to discover.
                waitAction.config.max_wait_duration = '30d'
                waitAction.config.wake_plan = { streams: ['person'], timers: [] }

                const result = await handler.execute({
                    invocation: waitInvocation,
                    action: waitAction,
                    result: createInvocationResult(waitInvocation),
                })

                expect(result.scheduledAt).toEqual(DateTime.utc().plus({ days: 30 }))
            })

            // Verbatim analyzer output for the two live prod-eu conditions that depend on the poll
            // today, dumped from analyze_wait_condition. Hand-written bytecode would only prove the
            // executor works on bytecode we invented; these prove the actual Python-to-TypeScript
            // chain lands on the right instant for the flows we're about to change.
            it.each([
                [
                    'team 84676 trial reminder (offset from a second person property)',
                    [
                        '_H',
                        1,
                        33,
                        86400,
                        32,
                        'trial_reminder_days',
                        32,
                        'properties',
                        32,
                        'person',
                        1,
                        3,
                        2,
                        'toInt',
                        1,
                        33,
                        1,
                        2,
                        'coalesce',
                        2,
                        8,
                        32,
                        'trial_expiration_at',
                        32,
                        'properties',
                        32,
                        'person',
                        1,
                        3,
                        2,
                        'toDateTime',
                        1,
                        2,
                        'toUnixTimestamp',
                        1,
                        7,
                        2,
                        'fromUnixTimestamp',
                        1,
                    ],
                    { trial_expiration_at: '2025-01-08T00:00:00Z', trial_reminder_days: '3' },
                    { days: 4 },
                ],
                [
                    'team 23252 coupon (14 days since last seen)',
                    [
                        '_H',
                        1,
                        32,
                        'day',
                        33,
                        14,
                        32,
                        'last_seen_at',
                        32,
                        'properties',
                        32,
                        'person',
                        1,
                        3,
                        2,
                        'toDateTime',
                        1,
                        2,
                        'dateAdd',
                        3,
                    ],
                    { last_seen_at: '2025-01-01T00:00:00Z' },
                    { days: 14 },
                ],
            ])('schedules %s from real analyzer output', async (_name, timer, properties, expected) => {
                waitAction.config.max_wait_duration = '30d'
                waitAction.config.wake_plan = { streams: ['person'], timers: [timer] }
                waitInvocation.person = { properties } as any

                const result = await handler.execute({
                    invocation: waitInvocation,
                    action: waitAction,
                    result: createInvocationResult(waitInvocation),
                })

                expect(result.scheduledAt!.toISO()).toEqual(DateTime.utc().plus(expected).toISO())
            })

            it('keeps the polling cap when the plan could not be derived', async () => {
                // Fail closed: an unsupported plan means we could not prove how this wait gets woken,
                // so it must behave exactly as it does today rather than trusting a deadline.
                waitAction.config.max_wait_duration = '30d'
                waitAction.config.wake_plan = {
                    streams: [],
                    timers: [],
                    unsupported_reason: 'clock reference in unsupported position',
                }

                const result = await handler.execute({
                    invocation: waitInvocation,
                    action: waitAction,
                    result: createInvocationResult(waitInvocation),
                })

                expect(result.scheduledAt).toEqual(DateTime.utc().plus({ minutes: 10 }))
            })
        })

        it('marks the wait as re-parked when its condition does not match', async () => {
            // The default condition does not match, so the wait re-parks and records that it has
            // polled at least once — without counting a poll-only advance.
            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.scheduledAt).toBeDefined()
            expect(waitInvocation.state.currentAction!.pollReparked).toBe(true)
            expect(await pollOnlyAdvanceCount()).toBe(0)
        })

        it('counts a poll-only advance when a re-parked wait matches on a later re-check', async () => {
            // Evaluable event-name filter that matches the example invocation's `test` event.
            waitAction.config.condition = {
                filters: {
                    bytecode: ['_H', 1, 32, 'test', 32, 'event', 1, 1, 11],
                    events: [{ id: 'test', name: 'test', type: 'events', order: 0 }],
                },
            }
            // The wait already re-parked at least once and the matcher did not wake it: the periodic
            // re-check is what found the condition true.
            waitInvocation.state.currentAction!.pollReparked = true

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.nextAction).toEqual(findActionById(waitInvocation.hogFlow, 'matched_target'))
            expect(await pollOnlyAdvanceCount()).toBe(1)
            // Must name the flow, not the run: attributing the residual is the counter's whole job.
            expect(await pollOnlyAdvanceLabels()).toEqual({
                team_id: waitInvocation.hogFlow.team_id,
                hog_flow_id: waitInvocation.hogFlow.id,
            })
        })

        it('does not count an evaluate-on-entry match (the wait never re-parked)', async () => {
            // Evaluable event-name filter that matches the example invocation's `test` event.
            waitAction.config.condition = {
                filters: {
                    bytecode: ['_H', 1, 32, 'test', 32, 'event', 1, 1, 11],
                    events: [{ id: 'test', name: 'test', type: 'events', order: 0 }],
                },
            }
            // pollReparked is unset: the condition was already true on entry, which polling did not catch.

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.nextAction).toEqual(findActionById(waitInvocation.hogFlow, 'matched_target'))
            expect(await pollOnlyAdvanceCount()).toBe(0)
        })

        it('does not count a matcher (eventMatched) wake as poll-only', async () => {
            waitInvocation.state.currentAction!.pollReparked = true
            waitInvocation.state.currentAction!.eventMatched = true

            await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(await pollOnlyAdvanceCount()).toBe(0)
        })

        it('records a rekey wake as advanced and consumes the one-shot flag when the merge makes the condition match', async () => {
            // A merge re-keyed this parked wait onto the survivor and woke it (rekeyWake). The re-check
            // now finds the condition true. Consuming the flag is what keeps the next re-check from
            // re-emitting the outcome — without it a re-parked wake would inflate the churn metric.
            waitAction.config.condition = {
                filters: {
                    bytecode: ['_H', 1, 32, 'test', 32, 'event', 1, 1, 11],
                    events: [{ id: 'test', name: 'test', type: 'events', order: 0 }],
                },
            }
            waitInvocation.state.currentAction!.rekeyWake = true

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.nextAction).toEqual(findActionById(waitInvocation.hogFlow, 'matched_target'))
            expect(await rekeyWakeCount('advanced')).toBe(1)
            expect(await rekeyWakeCount('reparked')).toBe(0)
            expect(waitInvocation.state.currentAction!.rekeyWake).toBe(false)
        })

        it('records a rekey wake as reparked and consumes the one-shot flag when the merge does not satisfy the wait', async () => {
            // The default condition still does not match after the re-key, so waking was wasted churn.
            waitInvocation.state.currentAction!.rekeyWake = true

            const result = await handler.execute({
                invocation: waitInvocation,
                action: waitAction,
                result: createInvocationResult(waitInvocation),
            })

            expect(result.scheduledAt).toBeDefined()
            expect(await rekeyWakeCount('reparked')).toBe(1)
            expect(await rekeyWakeCount('advanced')).toBe(0)
            expect(waitInvocation.state.currentAction!.rekeyWake).toBe(false)
        })
    })
})
