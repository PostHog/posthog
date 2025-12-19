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
        })
    })
})
