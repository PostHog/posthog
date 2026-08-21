import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'

import { CdpUsageReporterService } from './cdp-usage-reporter.service'

describe('CdpUsageReporterService', () => {
    let ingested: UsageRecordInput[][]
    let client: UsageIngestionClient

    beforeEach(() => {
        jest.useFakeTimers()
        ingested = []
        client = {
            ingest: jest.fn((records: UsageRecordInput[]) => {
                ingested.push(records)
                return Promise.resolve()
            }),
        } as unknown as UsageIngestionClient
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('collapses repeats of a record ID into one billed invocation', async () => {
        const reporter = new CdpUsageReporterService(client, () => true)
        reporter.reportBillableInvocation({ teamId: 1, recordId: 'event:abc', kind: 'destination' })
        reporter.reportBillableInvocation({ teamId: 1, recordId: 'event:abc', kind: 'destination' })
        await reporter.flush()

        expect(ingested[0]).toEqual([
            expect.objectContaining({
                recordId: 'event:abc',
                teamId: 1,
                quantity: 2,
                usageKey: 'cdp_billable_invocations',
                dimensions: { kind: 'destination' },
            }),
        ])
    })

    it('flushes on its own schedule without a caller flush', async () => {
        const reporter = new CdpUsageReporterService(client, () => true, 1000)
        reporter.reportBillableInvocation({ teamId: 1, recordId: 'event:abc', kind: 'destination' })

        expect(client.ingest).not.toHaveBeenCalled()

        jest.advanceTimersByTime(1000)
        await Promise.resolve()

        expect(client.ingest).toHaveBeenCalledTimes(1)
    })

    it('records nothing for a team the matcher excludes', async () => {
        const reporter = new CdpUsageReporterService(client, (teamId) => teamId === 2, 1000)
        reporter.reportBillableInvocation({ teamId: 1, recordId: 'event:abc', kind: 'destination' })
        await reporter.flush()

        expect(client.ingest).not.toHaveBeenCalled()
    })
})
