import api from 'lib/api'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import posthog from 'posthog-js'
import { PluginImage, PluginImageSize } from 'scenes/plugins/plugin/PluginImage'

import { PluginConfigTypeNew, PluginType } from '~/types'

export function capturePluginEvent(event: string, plugin: PluginType, pluginConfig: PluginConfigTypeNew): void {
    posthog.capture(event, {
        plugin_id: plugin.id,
        plugin_name: plugin.name,
        plugin_config_id: pluginConfig.id,
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
    plugin: PluginType
    imageSize?: PluginImageSize
}

export function RenderApp({ plugin, imageSize }: RenderAppProps): JSX.Element {
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
