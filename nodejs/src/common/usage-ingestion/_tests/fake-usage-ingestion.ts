import { connectNodeAdapter } from '@connectrpc/connect-node'
import http2 from 'http2'
import { AddressInfo } from 'net'

import { UsageIngestion } from '~/common/generated/usage-ingestion/usage_ingestion/v1/service_pb'

import { UsageIngestionClient } from '../client'

export type IngestedUsage = { teamId: number; usageKey: string; quantity: number; recordId: string }

export class FakeUsageIngestion {
    readonly accepted: IngestedUsage[] = []
    private server: http2.Http2Server | null = null
    private readonly sessions = new Set<http2.ServerHttp2Session>()

    async start(): Promise<UsageIngestionClient> {
        this.server = http2.createServer(
            connectNodeAdapter({
                routes: (router) =>
                    router.service(UsageIngestion, {
                        ingestBillingUsage: (request) => {
                            const fresh = request.records.filter(
                                (record) => !this.accepted.some((seen) => seen.recordId === record.recordId)
                            )
                            this.accepted.push(
                                ...fresh.map((record) => ({
                                    teamId: Number(record.teamId),
                                    usageKey: record.usageKey,
                                    quantity: Number(record.quantity),
                                    recordId: record.recordId,
                                }))
                            )
                            return { acceptedRecordIds: request.records.map((record) => record.recordId) }
                        },
                    }),
            })
        )
        this.server.on('session', (session) => {
            this.sessions.add(session)
            session.on('close', () => this.sessions.delete(session))
        })
        await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve))
        const { port } = this.server.address() as AddressInfo
        return new UsageIngestionClient({ addr: `127.0.0.1:${port}`, producerId: 'cdp-test' })
    }

    async stop(): Promise<void> {
        for (const session of this.sessions) {
            session.destroy()
        }
        await new Promise<void>((resolve) => (this.server ? this.server.close(() => resolve()) : resolve()))
    }
}
