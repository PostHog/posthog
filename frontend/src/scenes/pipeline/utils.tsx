import { LemonSkeleton } from '@posthog/lemon-ui'
import api from 'lib/api'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'

import { BatchExportConfiguration, LogEntryLevel, PluginType } from '~/types'

import { PluginImage, PluginImageSize } from './PipelinePluginImage'

export function captureBatchExportEvent(event: string, batchExport: BatchExportConfiguration): void {
    posthog.capture(event, {
        batch_export_id: batchExport.id,
        batch_export_name: batchExport.name,
        batch_export_destination_type: batchExport.destination.type,
    })
}

type RenderAppProps = {
    /** If the plugin is null, a skeleton will be rendered. */
    plugin: PluginType | null
    imageSize?: PluginImageSize
}

export function RenderApp({ plugin, imageSize = 'small' }: RenderAppProps): JSX.Element {
    if (!plugin) {
        return <LemonSkeleton className="w-15 h-15" />
    }

    return (
        <div className="flex gap-4 items-center">
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
                {plugin.url && plugin.plugin_type !== 'inline' ? (
                    <Link to={plugin.url} target="_blank">
                        <PluginImage plugin={plugin} size={imageSize} />
                    </Link>
                ) : (
                    <span>
                        <PluginImage plugin={plugin} size={imageSize} />
                    </span>
                )}
            </Tooltip>
        </div>
    )
}

export function LogLevelDisplay(level: LogEntryLevel): JSX.Element {
    let color: string | undefined
    switch (level) {
        case 'DEBUG':
            color = 'text-muted'
            break
        case 'LOG':
            color = 'text-text-3000'
            break
        case 'INFO':
            color = 'text-accent'
            break
        case 'WARNING':
        case 'WARN':
            color = 'text-warning'
            break
        case 'ERROR':
            color = 'text-danger'
            break
        default:
            break
    }
    return <span className={color}>{level}</span>
}

export async function loadPluginsFromUrl(url: string): Promise<Record<number, PluginType>> {
    const results: PluginType[] = await api.loadPaginatedResults<PluginType>(url)
    return Object.fromEntries(results.map((plugin) => [plugin.id, plugin]))
}
