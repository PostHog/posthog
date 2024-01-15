import { LemonSkeleton } from '@posthog/lemon-ui'
import api from 'lib/api'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'
import { PluginImage, PluginImageSize } from 'scenes/plugins/plugin/PluginImage'

import { BatchExportConfiguration, PluginConfigTypeNew, PluginLogEntryType, PluginType } from '~/types'

import { PipelineAppLogLevel } from './pipelineAppLogsLogic'

export function capturePluginEvent(event: string, plugin: PluginType, pluginConfig: PluginConfigTypeNew): void {
    posthog.capture(event, {
        plugin_id: plugin.id,
        plugin_name: plugin.name,
        plugin_config_id: pluginConfig.id,
    })
}
export function captureBatchExportEvent(event: string, batchExport: BatchExportConfiguration): void {
    posthog.capture(event, {
        batch_export_id: batchExport.id,
        batch_export_name: batchExport.name,
        batch_export_destination_type: batchExport.destination.type,
    })
}

const PAGINATION_DEFAULT_MAX_PAGES = 10
export async function loadPaginatedResults(
    url: string | null,
    maxIterations: number = PAGINATION_DEFAULT_MAX_PAGES
): Promise<any[]> {
    let results: any[] = []
    for (let i = 0; i <= maxIterations; ++i) {
        if (!url) {
            break
        }

        const { results: partialResults, next } = await api.get(url)
        results = results.concat(partialResults)
        url = next
    }
    return results
}

type RenderAppProps = {
    /** If the plugin is null, a skeleton will be rendered. */
    plugin: PluginType | null
    imageSize?: PluginImageSize
}

export function RenderApp({ plugin, imageSize }: RenderAppProps): JSX.Element {
    if (!plugin) {
        return <LemonSkeleton className="w-15 h-15" />
    }

    return (
        <div className="flex items-center gap-4">
            <Tooltip
                title={
                    <>
                        {plugin.name}
                        <br />
                        {plugin.description}
                        <br />
                        {plugin.url ? 'Click to view app source code' : 'No source code available'}
                    </>
                }
            >
                {plugin.url ? (
                    <Link to={plugin.url} target="_blank">
                        <PluginImage plugin={plugin} size={imageSize} />
                    </Link>
                ) : (
                    <PluginImage plugin={plugin} size={imageSize} /> // TODO: tooltip doesn't work on this
                )}
            </Tooltip>
        </div>
    )
}

export const logLevelToTypeFilter = (level: PipelineAppLogLevel): PluginLogEntryType => {
    switch (level) {
        case PipelineAppLogLevel.Debug:
            return PluginLogEntryType.Debug
        case PipelineAppLogLevel.Error:
            return PluginLogEntryType.Error
        case PipelineAppLogLevel.Info:
            return PluginLogEntryType.Info
        case PipelineAppLogLevel.Log:
            return PluginLogEntryType.Log
        case PipelineAppLogLevel.Warning:
            return PluginLogEntryType.Warn
        default:
            throw new Error('unknown log level')
    }
}

export const logLevelsToTypeFilters = (levels: PipelineAppLogLevel[]): PluginLogEntryType[] =>
    levels.map((l) => logLevelToTypeFilter(l))

export const typeToLogLevel = (type: PluginLogEntryType): PipelineAppLogLevel => {
    switch (type) {
        case PluginLogEntryType.Debug:
            return PipelineAppLogLevel.Debug
        case PluginLogEntryType.Error:
            return PipelineAppLogLevel.Error
        case PluginLogEntryType.Info:
            return PipelineAppLogLevel.Info
        case PluginLogEntryType.Log:
            return PipelineAppLogLevel.Log
        case PluginLogEntryType.Warn:
            return PipelineAppLogLevel.Warning
        default:
            throw new Error('unknown log type')
    }
}

export function LogLevelDisplay(level: PipelineAppLogLevel): JSX.Element {
    let color: string | undefined
    switch (level) {
        case PipelineAppLogLevel.Debug:
            color = 'text-muted'
            break
        case PipelineAppLogLevel.Log:
            color = 'text-default'
            break
        case PipelineAppLogLevel.Info:
            color = 'text-primary'
            break
        case PipelineAppLogLevel.Warning:
            color = 'text-warning'
            break
        case PipelineAppLogLevel.Error:
            color = 'text-danger'
            break
        default:
            break
    }
    return <span className={color}>{level}</span>
}

export function LogTypeDisplay(type: PluginLogEntryType): JSX.Element {
    return LogLevelDisplay(typeToLogLevel(type))
}
