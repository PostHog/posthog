import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
import { HogFlow } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow, DBHogFunctionTemplate } from '../../types'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import {
    checkHogFlowQuotaLimits,
    counterHogFlowQuotaLimited,
    shouldBlockHogFlowDueToQuota,
} from './hogflow-quota-limiting'

describe('HogFlow Quota Limiting', () => {
    let mockQuotaLimiting: jest.Mocked<QuotaLimiting>
    let mockTemplateManager: jest.Mocked<HogFunctionTemplateManagerService>

    const paidTemplate: DBHogFunctionTemplate = {
        id: 'paid-uuid',
        template_id: 'template-webhook',
        sha: 'abc',
        name: 'Webhook',
        inputs_schema: [],
        bytecode: ['_h'],
        type: 'destination',
        free: false,
    }

    const freeTemplate: DBHogFunctionTemplate = {
        id: 'free-uuid',
        template_id: 'template-posthog-capture',
        sha: 'def',
        name: 'Capture a PostHog event',
        inputs_schema: [],
        bytecode: ['_h'],
        type: 'destination',
        free: true,
    }

    beforeEach(() => {
        mockQuotaLimiting = {
            isTeamQuotaLimited: jest.fn(),
        } as any

        mockTemplateManager = {
            getHogFunctionTemplates: jest.fn().mockResolvedValue({}),
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
        } as unknown as HogFlow

        it('should not limit workflow when team has no quota limits', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-webhook': paidTemplate,
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [
                    { type: 'function_email', config: { template_id: 'template-webhook' } } as any,
                    { type: 'function', config: { template_id: 'template-webhook' } } as any,
                ],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledTimes(2)
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledWith(teamId, 'workflow_emails')
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledWith(
                teamId,
                'workflow_destinations_dispatched'
            )
        })

        it('should limit workflow with paid email action when team has email quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_emails')
            })
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-webhook': paidTemplate,
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [
                    { type: 'function_email', config: { template_id: 'template-webhook' } } as any,
                    { type: 'function', config: { template_id: 'template-webhook' } } as any,
                ],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(true)
        })

        it('should limit workflow with paid destination action when team has destination quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-webhook': paidTemplate,
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [
                    { type: 'delay' } as any,
                    { type: 'function', config: { template_id: 'template-webhook' } } as any,
                    { type: 'function_email', config: { template_id: 'template-webhook' } } as any,
                ],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(true)
        })

        it('should not limit workflow with no billable action types', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'delay' } as any, { type: 'conditional_branch' } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
        })

        it('should not limit workflow with only free template actions', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-posthog-capture': freeTemplate,
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function', config: { template_id: 'template-posthog-capture' } } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
        })

        it('should limit workflow with mix of free and paid actions if any paid action hits quota', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-posthog-capture': freeTemplate,
                'template-webhook': paidTemplate,
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [
                    { type: 'function', config: { template_id: 'template-posthog-capture' } } as any,
                    { type: 'function', config: { template_id: 'template-webhook' } } as any,
                ],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(true)
        })

        it('should treat actions without template_id as billable', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function', config: {} } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(true)
        })

        it('should treat actions with unknown template as billable', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-unknown': null as any,
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function', config: { template_id: 'template-unknown' } } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting, mockTemplateManager)

            expect(result.isLimited).toBe(true)
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
            } as unknown as HogFlow,
        } as CyclotronJobInvocationHogFlow

        beforeEach(() => {
            jest.clearAllMocks()
            mockHogFunctionMonitoringService = {
                queueAppMetric: jest.fn(),
            } as any
            jest.spyOn(counterHogFlowQuotaLimited, 'labels').mockReturnValue({
                inc: jest.fn(),
            } as any)
        })

        it('should not block invocation when not quota limited', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-webhook': paidTemplate,
            })

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    actions: [{ type: 'function_email', config: { template_id: 'template-webhook' } } as any],
                },
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                hogFunctionTemplateManager: mockTemplateManager,
            })

            expect(result).toBe(false)
            expect(mockHogFunctionMonitoringService.queueAppMetric).not.toHaveBeenCalled()
            expect(counterHogFlowQuotaLimited.labels).not.toHaveBeenCalled()
        })

        it('should block invocation and emit metrics when quota limited', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_emails')
            })
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-webhook': paidTemplate,
            })

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    actions: [{ type: 'function_email', config: { template_id: 'template-webhook' } } as any],
                },
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                hogFunctionTemplateManager: mockTemplateManager,
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
                },
                'hog_flow'
            )
        })

        it('should not block workflow with only free actions even when quota is exceeded', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)
            mockTemplateManager.getHogFunctionTemplates.mockResolvedValue({
                'template-posthog-capture': freeTemplate,
            })

            const item: CyclotronJobInvocationHogFlow = {
                ...baseItem,
                hogFlow: {
                    ...baseItem.hogFlow,
                    actions: [{ type: 'function', config: { template_id: 'template-posthog-capture' } } as any],
                },
            }

            const result = await shouldBlockHogFlowDueToQuota(item, {
                quotaLimiting: mockQuotaLimiting,
                hogFunctionMonitoringService: mockHogFunctionMonitoringService,
                hogFunctionTemplateManager: mockTemplateManager,
            })

            expect(result).toBe(false)
            expect(mockQuotaLimiting.isTeamQuotaLimited).not.toHaveBeenCalled()
            expect(mockHogFunctionMonitoringService.queueAppMetric).not.toHaveBeenCalled()
        })
    })
})
