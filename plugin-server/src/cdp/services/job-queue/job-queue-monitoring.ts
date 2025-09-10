import { DateTime, Duration } from 'luxon'

import { CyclotronJobInvocation } from '~/cdp/types'

import { PluginsServerConfig } from '../../../types'
import { CdpRedis } from '../../redis'

export const BASE_REDIS_KEY =
    process.env.NODE_ENV == 'test' ? '@posthog-test/cyclotron-jobs' : '@posthog/cyclotron-jobs'
const REDIS_KEY_QUEUED = `${BASE_REDIS_KEY}/queue`

export class CyclotronJobQueueMonitoring {
    constructor(
        private config: PluginsServerConfig,
        private redis: CdpRedis
    ) {}

    private keyForFunction(id: string) {
        return `${REDIS_KEY_QUEUED}/${id}`
    }

    public async markScheduledInvocations(invocations: CyclotronJobInvocation[]) {
        // TODO: Maybe only observe scheduled ones?
        // NOTE: Need to add some special handling for hog flow actions to get the current actionID
        const invocationsByFunctionId = invocations.reduce(
            (acc, x) => {
                acc[x.functionId] = acc[x.functionId] ?? []
                acc[x.functionId].push([(x.queueScheduledAt ?? DateTime.now()).toMillis(), x.id])
                return acc
            },
            {} as Record<string, [number, string][]>
        )

        await this.redis.usePipeline({ name: 'cyclotron-job-observe', failOpen: true }, (pipeline) => {
            Object.entries(invocationsByFunctionId).forEach(([functionId, invocationIds]) => {
                pipeline.zadd(this.keyForFunction(functionId), ...invocationIds.flatMap((x) => x))
            })
        })

        return
    }

    public async unmarkScheduledInvocations(invocations: CyclotronJobInvocation[]) {
        const invocationsByFunctionId = invocations.reduce(
            (acc, x) => {
                acc[x.functionId] = acc[x.functionId] ?? []
                acc[x.functionId].push(x.id)
                return acc
            },
            {} as Record<string, string[]>
        )

        await this.redis.usePipeline({ name: 'cyclotron-job-observe', failOpen: true }, (pipeline) => {
            Object.entries(invocationsByFunctionId).forEach(([functionId, invocationIds]) => {
                pipeline.zrem(this.keyForFunction(functionId), ...invocationIds)
            })
        })
    }

    public async getFunctionInvocations(id: string, startTime: number): Promise<Record<string, number>> {
        const res = await this.redis.useClient({ name: 'cyclotron-job-observe', failOpen: true }, (client) => {
            return client.zrangebyscore(this.keyForFunction(id), startTime, Infinity, 'WITHSCORES')
        })

        const functionInvocations: Record<string, number> = {}

        // Group by two

        if (!res) {
            return {}
        }

        for (let i = 0; i < res?.length; i += 2) {
            functionInvocations[res[i]] = Number(res[i + 1])
        }

        return functionInvocations
    }

    public async getScheduledFunctionInvocations(id: string, offset?: Duration): Promise<Record<string, number>> {
        const startTime = DateTime.now()
            .plus(offset ?? { seconds: 0 })
            .toMillis()
        return this.getFunctionInvocations(id, startTime)
    }

    public async countFunctionInvocations(id: string, startTime: number): Promise<number> {
        const res = await this.redis.useClient({ name: 'cyclotron-job-observe', failOpen: true }, (client) =>
            client.zcount(this.keyForFunction(id), startTime, Infinity)
        )
        return res ?? 0
    }

    public async countScheduledFunctionInvocations(id: string, offset?: Duration): Promise<number> {
        const startTime = DateTime.now()
            .plus(offset ?? { seconds: 0 })
            .toMillis()
        return this.countFunctionInvocations(id, startTime)
    }
}
