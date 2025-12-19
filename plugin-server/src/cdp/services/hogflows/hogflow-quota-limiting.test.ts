import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
import { HogFlow } from '../../../schema/hogflow'
import { checkHogFlowQuotaLimits } from './hogflow-quota-limiting'

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
        } as unknown as HogFlow

        it('should not limit workflow when team has no quota limits', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(false)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_email' } as any, { type: 'function' } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(result.limitedBy).toBeUndefined()
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
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
            expect(result.limitedBy).toBe('workflow_emails')
        })

        it('should limit workflow with destination action when team has destination quota limit', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                return Promise.resolve(resource === 'workflow_destinations_dispatched')
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'delay' } as any, { type: 'function' } as any, { type: 'function_email' } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
            expect(result.limitedBy).toBe('workflow_destinations_dispatched')
        })

        it('should break early and return email limit when both limits exist', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function_email' } as any, { type: 'function' } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(true)
            // Should return email limit since it's checked first
            expect(result.limitedBy).toBe('workflow_emails')
        })

        it('should not limit workflow without email or destination actions even when quotas exist', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'delay' } as any, { type: 'conditional_branch' } as any],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(result.limitedBy).toBeUndefined()
        })

        it('should handle empty actions array', async () => {
            mockQuotaLimiting.isTeamQuotaLimited.mockResolvedValue(true)

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [],
            }

            const result = await checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            expect(result.isLimited).toBe(false)
            expect(result.limitedBy).toBeUndefined()
        })

        it('should check quotas in parallel', async () => {
            let resolveEmail: any
            let resolveDestination: any

            const emailPromise = new Promise((resolve) => {
                resolveEmail = resolve
            })
            const destinationPromise = new Promise((resolve) => {
                resolveDestination = resolve
            })

            mockQuotaLimiting.isTeamQuotaLimited.mockImplementation((_teamId, resource) => {
                if (resource === 'workflow_emails') {
                    return emailPromise as any
                }
                return destinationPromise as any
            })

            const hogFlow: HogFlow = {
                ...baseHogFlow,
                actions: [{ type: 'function' } as any],
            }

            const resultPromise = checkHogFlowQuotaLimits(hogFlow, teamId, mockQuotaLimiting)

            // Both quota checks should be called immediately
            expect(mockQuotaLimiting.isTeamQuotaLimited).toHaveBeenCalledTimes(2)

            // Resolve both promises
            resolveEmail(false)
            resolveDestination(false)

            const result = await resultPromise
            expect(result.isLimited).toBe(false)
        })
    })
})
