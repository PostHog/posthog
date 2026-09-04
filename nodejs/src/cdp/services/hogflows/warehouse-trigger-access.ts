import {
    DWH_SOURCE_TABLE_PROPERTY,
    HogFlow,
    WAREHOUSE_SOURCE_ROW_EVENT,
    WAREHOUSE_VIEW_ROW_EVENT,
} from '~/cdp/schema/hogflow'
import { HogFunctionInvocationGlobals } from '~/cdp/types'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { internalFetch } from '~/common/utils/request'

export interface WarehouseTriggerAccessConfig {
    INTERNAL_API_BASE_URL: string
    WORKFLOW_WAREHOUSE_ACCESS_JWT_SECRET: string
}

function warehouseSource(globals: HogFunctionInvocationGlobals): { triggerType: string; tableName: string } | null {
    const eventName = globals.event?.event
    if (eventName !== WAREHOUSE_SOURCE_ROW_EVENT && eventName !== WAREHOUSE_VIEW_ROW_EVENT) {
        return null
    }
    const tableName = globals.event?.properties?.[DWH_SOURCE_TABLE_PROPERTY]
    return {
        triggerType: eventName === WAREHOUSE_VIEW_ROW_EVENT ? 'data-warehouse-view' : 'data-warehouse-table',
        tableName: typeof tableName === 'string' ? tableName : '',
    }
}

function sourceKey(globals: HogFunctionInvocationGlobals): string {
    return JSON.stringify([globals.project.id, warehouseSource(globals)])
}

export class WarehouseTriggerAccess {
    private jwt: ScopedServiceJwt

    constructor(private config: WarehouseTriggerAccessConfig) {
        this.jwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOW_WAREHOUSE_ACCESS,
            config.WORKFLOW_WAREHOUSE_ACCESS_JWT_SECRET
        )
    }

    async forBatch(
        globals: HogFunctionInvocationGlobals[],
        flowsByTeam: Record<number, HogFlow[]>
    ): Promise<(flow: HogFlow, globals: HogFunctionInvocationGlobals) => boolean> {
        // Keep grants within this batch so a hot subscription cannot hide a later revocation.
        const allowedBySource = new Map<string, Set<string>>()
        const uniqueSources = new Map(
            globals.filter((item) => warehouseSource(item)).map((item) => [sourceKey(item), item])
        )

        for (const [key, item] of uniqueSources) {
            const source = warehouseSource(item)!
            const allowed = new Set<string>()
            allowedBySource.set(key, allowed)
            if (!source.tableName) {
                continue
            }
            const flows = (flowsByTeam[item.project.id] ?? []).filter(
                (flow) => flow.trigger.type === source.triggerType
            )
            for (let offset = 0; offset < flows.length; offset += 500) {
                const flowIds = flows.slice(offset, offset + 500).map((flow) => flow.id)
                const response = await internalFetch(
                    `${this.config.INTERNAL_API_BASE_URL}/api/projects/${item.project.id}/workflow_warehouse_access/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            Authorization: `Bearer ${this.jwt.mint({ team_id: item.project.id })}`,
                        },
                        body: JSON.stringify({
                            trigger_type: source.triggerType,
                            table_name: source.tableName,
                            flow_ids: flowIds,
                        }),
                        timeoutMs: 10_000,
                    }
                )
                if (response.status !== 200) {
                    await response.dump()
                    // Reject before queueing invocations so Kafka can retry without exposing rows.
                    throw new Error(`Warehouse workflow authorization failed (${response.status})`)
                }
                const result: unknown = await response.json()
                if (
                    !result ||
                    typeof result !== 'object' ||
                    !('allowed_flow_ids' in result) ||
                    !Array.isArray(result.allowed_flow_ids) ||
                    !result.allowed_flow_ids.every((id: unknown) => typeof id === 'string' && flowIds.includes(id))
                ) {
                    throw new Error('Invalid warehouse workflow authorization response')
                }
                for (const id of result.allowed_flow_ids) {
                    allowed.add(id)
                }
            }
        }

        return (flow, item) => {
            if (warehouseSource(item)) {
                return allowedBySource.get(sourceKey(item))?.has(flow.id) ?? false
            }
            return flow.trigger.type !== 'data-warehouse-table' && flow.trigger.type !== 'data-warehouse-view'
        }
    }
}
