import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { MetricsIngestionConsumerConfig, getDefaultMetricsIngestionConsumerConfig } from './config'
import { MetricsIngestionConsumer, MetricsIngestionConsumerDeps } from './metrics-ingestion-consumer'
import { MetricsIngestionMessage } from './types'

describe('MetricsIngestionConsumer', () => {
    describe('filterQuotaLimitedMessages', () => {
        let isTeamTokenQuotaLimited: jest.Mock

        const createConsumer = (overrides: Partial<MetricsIngestionConsumerConfig> = {}): MetricsIngestionConsumer => {
            const config: MetricsIngestionConsumerConfig = {
                ...getDefaultMetricsIngestionConsumerConfig(),
                ...overrides,
            }
            const deps: MetricsIngestionConsumerDeps = {
                teamManager: {} as any,
                quotaLimiting: { isTeamTokenQuotaLimited } as unknown as QuotaLimiting,
                outputs: {} as any,
            }
            return new MetricsIngestionConsumer(config, deps)
        }

        const createMessage = (teamId: number): MetricsIngestionMessage => ({
            token: `token-${teamId}`,
            teamId,
            message: { value: Buffer.from('test') } as any,
            bytesUncompressed: 1024,
            bytesCompressed: 512,
            recordCount: 1,
        })

        beforeEach(() => {
            isTeamTokenQuotaLimited = jest.fn().mockResolvedValue(false)
        })

        it('should allow messages when not quota limited', async () => {
            const consumer = createConsumer()
            const messages = [createMessage(1), createMessage(2)]

            const { quotaAllowedMessages, quotaDroppedMessages } =
                await consumer['filterQuotaLimitedMessages'](messages)

            expect(quotaAllowedMessages).toHaveLength(2)
            expect(quotaDroppedMessages).toHaveLength(0)
        })

        it('should drop quota-limited messages for non-exempt teams', async () => {
            isTeamTokenQuotaLimited.mockImplementation((token: string) => Promise.resolve(token === 'token-1'))
            const consumer = createConsumer()
            const messages = [createMessage(1), createMessage(2)]

            const { quotaAllowedMessages, quotaDroppedMessages } =
                await consumer['filterQuotaLimitedMessages'](messages)

            expect(quotaAllowedMessages).toHaveLength(1)
            expect(quotaAllowedMessages[0].teamId).toBe(2)
            expect(quotaDroppedMessages).toHaveLength(1)
            expect(quotaDroppedMessages[0].teamId).toBe(1)
        })

        it('should bypass quota enforcement for teams in METRICS_LIMITER_EXEMPT_TEAMS', async () => {
            isTeamTokenQuotaLimited.mockResolvedValue(true) // every token is quota limited
            const consumer = createConsumer({ METRICS_LIMITER_EXEMPT_TEAMS: '2' })
            const messages = [createMessage(1), createMessage(2)]

            const { quotaAllowedMessages, quotaDroppedMessages } =
                await consumer['filterQuotaLimitedMessages'](messages)

            expect(quotaAllowedMessages).toHaveLength(1)
            expect(quotaAllowedMessages[0].teamId).toBe(2)
            expect(quotaDroppedMessages).toHaveLength(1)
            expect(quotaDroppedMessages[0].teamId).toBe(1)
            // Exempt teams skip the quota lookup entirely
            expect(isTeamTokenQuotaLimited).toHaveBeenCalledTimes(1)
            expect(isTeamTokenQuotaLimited).toHaveBeenCalledWith('token-1', 'metrics_mb_ingested')
        })

        it('should enforce quota for everyone when the exemption list is empty', async () => {
            isTeamTokenQuotaLimited.mockResolvedValue(true)
            const consumer = createConsumer({ METRICS_LIMITER_EXEMPT_TEAMS: '' })
            const messages = [createMessage(1), createMessage(2)]

            const { quotaAllowedMessages, quotaDroppedMessages } =
                await consumer['filterQuotaLimitedMessages'](messages)

            expect(quotaAllowedMessages).toHaveLength(0)
            expect(quotaDroppedMessages).toHaveLength(2)
        })
    })
})
