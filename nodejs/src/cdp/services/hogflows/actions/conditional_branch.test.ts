import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { GroupsManagerService } from '~/cdp/services/managers/groups-manager.service'
import { compileHog } from '~/cdp/templates/compiler'
import { CyclotronJobInvocationHogFlow, HogBytecode } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils/hog-function-filtering'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { HogFlow, HogFlowAction } from '~/schema/hogflow'
import { TeamManager } from '~/utils/team-manager'
import { GroupReadRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { findActionById, findActionByType } from '../hogflow-utils'
import { ConditionalBranchHandler, checkConditions } from './conditional_branch'

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

    // Repro of the support-workflow bug: a $conversation_ticket_created event carries the
    // customer org via $groups, and the branch should match on that org's billing_plan.
    // Exercises the full chain the runtime uses: $groups -> group loading -> filter globals
    // -> compiled filter bytecode -> HogVM. organization sits at a non-zero group index in
    // real projects, so we use index 2 to catch index-alignment bugs.
    describe('organization (group) property conditions', () => {
        const TEAM_ID = 1
        const ORG_GROUP_INDEX = 2
        const ORG_KEY = 'org-key-123'

        let groupsManager: GroupsManagerService
        let billingPlanIsScale: HogBytecode

        const mockFetchGroupTypesByTeamIds = jest.fn()
        const mockFetchGroupsByKeys = jest.fn()

        beforeAll(async () => {
            // Same chain the frontend produces for "organization.billing_plan = scale":
            // property.type === 'group' compiles to group_<index>.properties.<key>
            billingPlanIsScale = await compileHog(
                `return ifNull(group_${ORG_GROUP_INDEX}.properties.billing_plan == 'scale', false)`
            )
        })

        beforeEach(() => {
            mockFetchGroupTypesByTeamIds.mockResolvedValue({
                [String(TEAM_ID)]: [{ group_type: 'organization', group_type_index: ORG_GROUP_INDEX }],
            })
            mockFetchGroupsByKeys.mockResolvedValue([
                {
                    team_id: TEAM_ID,
                    group_type_index: ORG_GROUP_INDEX,
                    group_key: ORG_KEY,
                    group_properties: { billing_plan: 'scale' },
                },
            ])

            const teamManager = {
                hasAvailableFeature: jest.fn().mockResolvedValue(true),
            } as unknown as TeamManager
            const groupRepository = {
                fetchGroupTypesByTeamIds: mockFetchGroupTypesByTeamIds,
                fetchGroupsByKeys: mockFetchGroupsByKeys,
            } as unknown as GroupReadRepository
            groupsManager = new GroupsManagerService(teamManager, groupRepository)
        })

        const filterGlobalsForEvent = async (eventProperties: Record<string, any>) => {
            const groups = await groupsManager.getGroupsForEvent(
                TEAM_ID,
                eventProperties,
                `http://localhost:8000/project/${TEAM_ID}`
            )
            return convertToHogFunctionFilterGlobal({
                event: { event: '$conversation_ticket_created', properties: eventProperties } as any,
                person: undefined,
                groups,
                variables: {},
            })
        }

        // properties is present so the bytecode actually runs (a bytecode-only filter
        // short-circuits to match without executing).
        const billingPlanCondition = () => ({
            filters: {
                properties: [
                    {
                        type: 'group',
                        group_type_index: ORG_GROUP_INDEX,
                        key: 'billing_plan',
                        value: 'scale',
                        operator: 'exact',
                    },
                ],
                bytecode: billingPlanIsScale,
            },
        })

        it.each([
            [
                'matches the branch when the org group on the event carries billing_plan',
                { $groups: { organization: ORG_KEY } },
                () => ({ nextAction: findActionById(invocation.hogFlow, 'condition_1') }),
            ],
            ['does not match when the event has no $groups (no org id on the event)', {}, () => ({})],
        ] as const)('%s', async (_, eventProps, expected) => {
            invocation.filterGlobals = await filterGlobalsForEvent(eventProps)
            action.config.conditions = [billingPlanCondition()]

            const result = await checkConditions(invocation, action)

            expect(result).toEqual(expected())
        })

        it('does not match when the org id is on the event but the group has no billing_plan', async () => {
            // The event carries $groups.organization, but the resolved group has no
            // billing_plan (e.g. the group key never received a $groupidentify, or the
            // key on the event does not match the stored group). The branch correctly
            // exits no-match — same symptom as a missing $groups, different root cause.
            mockFetchGroupsByKeys.mockResolvedValue([
                { team_id: TEAM_ID, group_type_index: ORG_GROUP_INDEX, group_key: ORG_KEY, group_properties: {} },
            ])
            const filterGlobals = await filterGlobalsForEvent({ $groups: { organization: ORG_KEY } })
            // The org id is still exposed on the event even though properties are empty.
            expect(filterGlobals[`group_${ORG_GROUP_INDEX}`]).toEqual({ properties: {} })
            expect(filterGlobals[`$group_${ORG_GROUP_INDEX}`]).toEqual(ORG_KEY)
            invocation.filterGlobals = filterGlobals
            action.config.conditions = [billingPlanCondition()]

            const result = await checkConditions(invocation, action)

            expect(result).toEqual({})
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
    })
})
