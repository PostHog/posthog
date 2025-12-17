import { Hub, PluginConfig, PluginMethodsConcrete, PostIngestionEvent } from '../../types'
import { processError } from '../../utils/db/error'
import { convertToOnEventPayload, mutatePostIngestionEventWithElementsList } from '../../utils/event'
import { pluginActionMsSummary } from '../metrics'

async function runSingleTeamPluginOnEvent(
    hub: Hub,
    event: PostIngestionEvent,
    pluginConfig: PluginConfig,
    onEvent: PluginMethodsConcrete['onEvent']
): Promise<{ backgroundTask: Promise<any> }> {
    if (!hub.pluginConfigsToSkipElementsParsing?.(pluginConfig.plugin_id)) {
        // Elements parsing can be extremely slow, so we skip it for some plugins that are manually marked as not needing it
        mutatePostIngestionEventWithElementsList(event)
    }

    const onEventPayload = convertToOnEventPayload(event)

    let error: any = null

    // Runs onEvent for a single plugin without any retries
    const timer = new Date()
    try {
        await onEvent(onEventPayload)
    } catch (e) {
        error = e
    }

    pluginActionMsSummary
        .labels(pluginConfig.plugin?.id.toString() ?? '?', 'onEvent', error ? 'error' : 'success')
        .observe(new Date().getTime() - timer.getTime())

    if (!error) {
        return {
            backgroundTask: hub.appMetrics.queueMetric({
                teamId: event.teamId,
                pluginConfigId: pluginConfig.id,
                category: 'onEvent',
                successes: 1,
            }),
        }
    } else {
        return {
            backgroundTask: Promise.all([
                processError(hub, pluginConfig, error, onEventPayload),
                hub.appMetrics.queueError(
                    {
                        teamId: event.teamId,
                        pluginConfigId: pluginConfig.id,
                        category: 'onEvent',
                        failures: 1,
                    },
                    {
                        error,
                        event,
                    }
                ),
            ]),
        }
    }
}

export async function runOnEvent(hub: Hub, event: PostIngestionEvent): Promise<{ backgroundTask: Promise<any> }[]> {
    // Runs onEvent for all plugins for this team in parallel
    const pluginMethodsToRun = await getPluginMethodsForTeam(hub, event.teamId, 'onEvent')

    return await Promise.all(
        pluginMethodsToRun.map(([pluginConfig, onEvent]) =>
            runSingleTeamPluginOnEvent(hub, event, pluginConfig, onEvent)
        )
    )
}
async function getPluginMethodsForTeam<M extends keyof PluginMethodsConcrete>(
    hub: Hub,
    teamId: number,
    method: M
): Promise<[PluginConfig, PluginMethodsConcrete[M]][]> {
    const pluginConfigs = hub.pluginConfigsPerTeam.get(teamId) || []
    if (pluginConfigs.length === 0) {
        return []
    }

    const methodsObtained = await Promise.all(
        pluginConfigs.map(async (pluginConfig) => [pluginConfig, await pluginConfig?.instance?.getPluginMethod(method)])
    )

    const methodsObtainedFiltered = methodsObtained.filter(([_, method]) => !!method) as [
        PluginConfig,
        PluginMethodsConcrete[M],
    ][]

    return methodsObtainedFiltered
}
