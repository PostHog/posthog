import { DateTime, Duration } from 'luxon'

import { CyclotronJobInvocation } from '~/cdp/types'
import { isHogFlowInvocation } from '~/cdp/utils'

import { CdpRedis } from '../../redis'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-queue' : '@posthog/hog-queue'
const REDIS_KEY_QUEUED = `${BASE_REDIS_KEY}/queue`

export class HogQueueMonitoring {
    constructor(private redis: CdpRedis) {}

    private keyForFunction(id: string) {
        return `${REDIS_KEY_QUEUED}/${id}`
    }

    private toObservations(invocations: CyclotronJobInvocation[]) {
        const now = DateTime.now()

        const invocationsByFunctionId = invocations.reduce(
            (acc, x) => {
                const time = (x.queueScheduledAt ?? now).toMillis()
                acc[x.functionId] = acc[x.functionId] ?? []
                acc[x.functionId].push([time, x.id])

                // Check if the invocation is CyclotronJobInvocationHogFlow and convert it
                if (isHogFlowInvocation(x) && x.state.currentAction?.id) {
                    const actionId = `${x.hogFlow.id}:${x.state.currentAction.id}`
                    acc[actionId] = acc[actionId] ?? []
                    acc[actionId].push([time, x.id])
                }

                return acc
            },
            {} as Record<string, [number, string][]>
        )

        return invocationsByFunctionId
    }

    public async markScheduledInvocations(invocations: CyclotronJobInvocation[]) {
        const invocationsByFunctionId = this.toObservations(invocations)

        await this.redis.usePipeline({ name: 'cyclotron-job-observe', failOpen: true }, (pipeline) => {
            Object.entries(invocationsByFunctionId).forEach(([functionId, invocationIds]) => {
                pipeline.zadd(this.keyForFunction(functionId), ...invocationIds.flatMap((x) => x))
            })
        })
    }

    public async unmarkScheduledInvocations(invocations: CyclotronJobInvocation[]) {
        const invocationsByFunctionId = this.toObservations(invocations)

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
        if (!res) {
            return {}
        }
        const functionInvocations: Record<string, number> = {}

        for (let i = 0; i < res.length; i += 2) {
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
