import api from 'lib/api'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'

import { PluginType } from '~/types'

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
}

export function RenderApp({ plugin }: RenderAppProps): JSX.Element {
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
                        <PluginImage plugin={plugin} />
                    </Link>
                ) : (
                    <PluginImage plugin={plugin} /> // TODO: tooltip doesn't work on this
                )}
            </Tooltip>
        </div>
    )
}
