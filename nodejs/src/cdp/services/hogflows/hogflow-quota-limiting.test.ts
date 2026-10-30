import { HogFlow } from '~/cdp/schema/hogflow'

import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
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

        it('should not limit workflow when team has no quota limits', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_email' } as any, { type: 'function' } as any],
                billable_action_types: ['function_email', 'function'],
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

        it('should limit workflow with email action when team has email quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_emails')
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_email' } as any, { type: 'function' } as any],
                billable_action_types: ['function_email', 'function'],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
        })

        const transactionalEmail = { type: 'function_email', config: { message_category_type: 'transactional' } }
        const marketingEmail = { type: 'function_email', config: { message_category_type: 'marketing' } }

        it.each([
            {
                name: 'only transactional emails are not limited',
                trigger: { type: 'event' },
                actions: [transactionalEmail, transactionalEmail],
                limitedResources: ['workflow_emails'],
                expected: false,
            },
            {
                name: 'an api trigger alone does not exempt an uncategorized email',
                trigger: { type: 'api' },
                actions: [{ type: 'function_email', config: {} }],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a marketing email next to a transactional one is limited',
                trigger: { type: 'event' },
                actions: [transactionalEmail, marketingEmail],
                limitedResources: ['workflow_emails'],
                expected: true,
            },
            {
                name: 'a destination next to transactional emails is still limited by the destination quota',
                trigger: { type: 'event' },
                actions: [transactionalEmail, { type: 'function', config: {} }],
                limitedResources: ['workflow_emails', 'workflow_destinations_dispatched'],
                expected: true,
            },
        ])('$name', async ({ trigger, actions, limitedResources, expected }) => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) =>
                Promise.resolve(limitedResources.includes(resource))
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
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_push' } as any, { type: 'function' } as any],
                billable_action_types: ['function_push', 'function'],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
        })

        it('should limit workflow with destination action when team has destination quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })

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

        it('should not limit workflow when billable_action_types is null', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function' } as any],
                billable_action_types: null,
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
        })

        it('should not check quota limits when billable_action_types is undefined', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function' } as any],
                billable_action_types: undefined,
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
        })

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
            })

            expect(result).toBe(false)
            expect(mockHogFunctionMonitoringService.queueAppMetric).not.toHaveBeenCalled()
            expect(counterHogFlowQuotaLimited.labels).not.toHaveBeenCalled()
        })

        it('should block invocation and emit metrics when quota limited', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_emails')
            })

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
            })

            expect(result).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
            expect(mockHogFunctionMonitoringService.queueAppMetric).not.toHaveBeenCalled()
        })
    })
})
