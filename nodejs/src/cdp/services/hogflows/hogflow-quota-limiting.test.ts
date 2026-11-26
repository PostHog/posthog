import { HogFlow } from '~/cdp/schema/hogflow'

import { QuotaLimiting, QuotaResource } from '../../../common/services/quota-limiting.service'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import {
    checkHogFlowQuotaLimits,
    counterHogFlowQuotaLimited,
    shouldBlockHogFlowDueToQuota,
} from './hogflow-quota-limiting'

describe('HogFlow Quota Limiting', () => {
    let mockQuotaLimiting: jest.Mocked<QuotaLimiting>

    beforeEach(() => {
        mockQuotaLimiting = {
            isTeamQuotaLimited: jest.fn(),
        } as any
    })

    describe('checkHogFlowQuotaLimits', () => {
        const teamId = 123
        const baseHogFlow: HogFlow = {
            id: 'test-flow',
            team_id: teamId,
            name: 'Test Flow',
            description: '',
            enabled: true,
            actions: [],
            trigger: { type: 'event' },
            billable_action_types: [],
        } as unknown as HogFlow

        it('should limit workflow with email action when team has email quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((team, resource) =>
                Promise.resolve(team === teamId && resource === 'workflow_emails')
            )

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_email' } as any, { type: 'function' } as any],
                billable_action_types: ['function_email', 'function'],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
        })

        // The workflow the transactional send API makes: an api trigger, its one email step, and an exit.
        const transactionalSendEmail = {
            id: 'transactional_email',
            type: 'function_email',
            config: { message_category_type: 'transactional' },
        }
        const transactionalCategoryEmail = {
            id: 'email_1',
            type: 'function_email',
            config: { message_category_type: 'transactional' },
        }
        const marketingEmail = { id: 'email_2', type: 'function_email', config: { message_category_type: 'marketing' } }
        const webhook = { id: 'webhook_1', type: 'function', config: {} }
        const pageview = { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } }
        const eventTrigger = (...events: Record<string, unknown>[]): Record<string, unknown> => ({
            type: 'event',
            filters: { events },
        })
        const supportReply = {
            type: 'internal-event',
            filters: { source: 'internal-events', events: [{ id: '$conversation_message_sent', type: 'events' }] },
        }

        it.each<{
            name: string
            trigger: Record<string, unknown>
            actions: Record<string, unknown>[]
            limitedResources: QuotaResource[]
            expected: boolean
        }>([
            {
                name: 'a team under every quota is not limited',
                trigger: pageview,
                actions: [marketingEmail, webhook],
                limitedResources: [],
                expected: false,
            },
            {
                name: 'a webhook alone is not limited by the email quota',
                trigger: pageview,
                actions: [webhook],
                limitedResources: ['workflow_emails'],
                expected: false,
            },
            {
                name: 'a push send alone is limited by the destination quota',
                trigger: pageview,
                actions: [{ id: 'push_1', type: 'function_push', config: {} }],
                limitedResources: ['workflow_destinations_dispatched'],
                expected: true,
            },
            {
                name: 'a transactional send is not limited',
                trigger: { type: 'api' },
                actions: [transactionalSendEmail],
                limitedResources: ['workflow_emails'],
                expected: false,
            },
            {
                name: 'an api trigger alone does not exempt an uncategorized email',
                trigger: { type: 'api' },
                actions: [{ id: 'email_1', type: 'function_email', config: {} }],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a workflow email in a transactional category is limited',
                trigger: pageview,
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a transactional support reply is not limited',
                trigger: supportReply,
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: false,
            },
            {
                name: 'a support reply whose internal event entry names only the event is not limited',
                trigger: {
                    type: 'internal-event',
                    filters: { source: 'internal-events', events: [{ id: '$conversation_message_sent' }] },
                },
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: false,
            },
            {
                name: 'a support reply next to another internal event is limited',
                trigger: {
                    type: 'internal-event',
                    filters: {
                        source: 'internal-events',
                        events: [{ id: '$conversation_message_sent' }, { id: '$slack_message_posted' }],
                    },
                },
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a transactional ticket update on an analytics trigger is not limited',
                trigger: eventTrigger({ id: '$conversation_ticket_created', type: 'events' }),
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: false,
            },
            {
                name: 'an event named like a support event is limited',
                trigger: eventTrigger({ id: '$conversation_spring_sale', type: 'events' }),
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'an analytics entry without a type matches any event and is limited',
                trigger: eventTrigger({ id: '$conversation_ticket_created' }),
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a support event next to another event is limited',
                trigger: eventTrigger(
                    { id: '$conversation_ticket_created', type: 'events' },
                    { id: '$pageview', type: 'events' }
                ),
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a support event with an action filter is limited',
                trigger: {
                    type: 'event',
                    filters: { events: [{ id: '$conversation_ticket_created', type: 'events' }], actions: [{ id: 1 }] },
                },
                actions: [transactionalCategoryEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a marketing email in a support workflow is limited',
                trigger: supportReply,
                actions: [transactionalCategoryEmail, marketingEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a webhook in a support workflow is still limited by the destination quota',
                trigger: supportReply,
                actions: [transactionalCategoryEmail, webhook],
                limitedResources: ['workflow_destinations_dispatched'],
                expected: true,
            },
        ])('$name', async ({ trigger, actions, limitedResources, expected }) => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((team, resource) =>
                Promise.resolve(team === teamId && limitedResources.includes(resource))
            )

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                trigger,
                actions,
                billable_action_types: [...new Set(actions.map((action) => action.type))],
            } as unknown as HogFlow

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(expected)
        })

        it('should limit workflow with push action when team has destination quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((team, resource) =>
                Promise.resolve(team === teamId && resource === 'workflow_destinations_dispatched')
            )

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_push' } as any, { type: 'function' } as any],
                billable_action_types: ['function_push', 'function'],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
        })

        it('should limit workflow with destination action when team has destination quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((team, resource) =>
                Promise.resolve(team === teamId && resource === 'workflow_destinations_dispatched')
            )

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'delay' } as any, { type: 'function' } as any, { type: 'function_email' } as any],
                billable_action_types: ['function', 'function_email'],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
        })

        it('should not limit workflow with no billable action types', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'delay' } as any, { type: 'conditional_branch' } as any],
                billable_action_types: [],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
        })

        it.each([null, undefined])(
            'should not limit workflow when billable_action_types is %s',
            async (billableActionTypes) => {
                mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

                const hogFlow: HogFlow = {
                    ...baseHogFlow,
                    actions: [{ type: 'function' } as any],
                    billable_action_types: billableActionTypes,
                }

                const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

                expect(result.isLimited).toBe(false)
            }
        )

        it('should only check relevant quota limits based on billable action types', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function' } as any, { type: 'delay' } as any],
                billable_action_types: ['function'],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledTimes(2)
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledWith(teamId, 'workflow_emails')
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledWith(
                teamId,
                'workflow_destinations_dispatched'
            )
        })
    })

    describe('shouldBlockHogFlowDueToQuota', () => {
        let mockHogFunctionMonitoringService: jest.Mocked<HogFunctionMonitoringService>
        let mockWorkflowsActivationReporter: { report: jest.Mock }
        const teamId = 123
        const baseItem: CyclotronJobInvocationHogFlow = {
            teamId,
            functionId: 'test-flow-id',
            hogFlow: {
                id: 'test-flow',
                team_id: teamId,
                name: 'Test Flow',
                description: '',
                enabled: true,
                actions: [],
                trigger: { type: 'event' },
                billable_action_types: [],
                version: 4,
            } as unknown as HogFlow,
        } as CyclotronJobInvocationHogFlow

        beforeEach(() => {
            jest.clearAllMocks()
            mockHogFunctionMonitoringService = {
                queueAppMetric: jest.fn(),
            } as any
            mockWorkflowsActivationReporter = { report: jest.fn() }
            // Reset the counter spy
            jest.spyOn(counterHogFlowQuotaLimited, 'labels').mockReturnValue({
                inc: jest.fn(),
            } as any)
        })

        it('should not block invocation when not quota limited', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    billable_action_types: ['function_email'],
                },
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                workflowsActivationReporter: mockWorkflowsActivationReporter,
            })

            expect(result).toBe(false)
            expect(mockHogFunctionMonitoringService.queueAppMetric).not.toHaveBeenCalled()
            expect(counterHogFlowQuotaLimited.labels).not.toHaveBeenCalled()
            expect(mockWorkflowsActivationReporter.report).not.toHaveBeenCalled()
        })

        it.each([
            [
                'an email send on the email quota',
                'workflow_emails',
                ['function_email'],
                [
                    [
                        teamId,
                        'workflows send blocked',
                        { reason: 'quota_limited', channel: 'email', workflow_id: 'test-flow-id' },
                    ],
                ],
            ],
            ['a webhook on the destination quota', 'workflow_destinations_dispatched', ['function'], []],
            [
                'an email send next to a webhook on the destination quota',
                'workflow_destinations_dispatched',
                ['function_email', 'function'],
                [
                    [
                        teamId,
                        'workflows send blocked',
                        { reason: 'quota_limited', channel: 'email', workflow_id: 'test-flow-id' },
                    ],
                ],
            ],
        ] as const)('should block %s and emit metrics', async (_name, limitedResource, actionTypes, reports) => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === limitedResource)
            })

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    billable_action_types: [...actionTypes],
                },
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                workflowsActivationReporter: mockWorkflowsActivationReporter,
            })

            expect(result).toBe(true)
            expect(counterHogFlowQuotaLimited.labels).toHaveBeenCalledWith({ team_id: teamId })
            expect(mockHogFunctionMonitoringService.queueAppMetric).toHaveBeenCalledWith(
                {
                    team_id: teamId,
                    app_source_id: 'test-flow-id',
                    metric_kind: 'failure',
                    metric_name: 'quota_limited',
                    count: 1,
                    app_source_version: { id: expect.any(String), version: 4 },
                },
                'hog_flow'
            )
            expect(mockWorkflowsActivationReporter.report.mock.calls).toEqual(reports)
        })

        it('should report a blocked email send when the destination quota stops a support reply next to a webhook', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((team, resource) =>
                Promise.resolve(team === teamId && resource === 'workflow_destinations_dispatched')
            )

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    trigger: {
                        type: 'internal-event',
                        filters: {
                            source: 'internal-events',
                            events: [{ id: '$conversation_message_sent', type: 'events' }],
                        },
                    },
                    actions: [
                        { id: 'email_1', type: 'function_email', config: { message_category_type: 'transactional' } },
                        { id: 'webhook_1', type: 'function', config: {} },
                    ],
                    billable_action_types: ['function_email', 'function'],
                } as unknown as HogFlow,
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                workflowsActivationReporter: mockWorkflowsActivationReporter,
            })

            expect(result).toBe(true)
            expect(mockWorkflowsActivationReporter.report).toHaveBeenCalledWith(teamId, 'workflows send blocked', {
                reason: 'quota_limited',
                channel: 'email',
                workflow_id: 'test-flow-id',
            })
        })

        it('should handle workflow with no billable actions', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    billable_action_types: [],
                },
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                workflowsActivationReporter: mockWorkflowsActivationReporter,
            })

            expect(result).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
            expect(mockHogFunctionMonitoringService.queueAppMetric).not.toHaveBeenCalled()
        })
    })
})
