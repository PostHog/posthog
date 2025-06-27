import { LemonMenuItem, LemonSkeleton, LemonTableColumn, lemonToast } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import api from 'lib/api'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import posthog from 'posthog-js'
import { urls } from 'scenes/urls'

import {
    BatchExportConfiguration,
    LogEntryLevel,
    PipelineNodeTab,
    PipelineStage,
    PluginConfigTypeNew,
    PluginType,
} from '~/types'

import { pipelineAccessLogic } from './pipelineAccessLogic'
import { PluginImage, PluginImageSize } from './PipelinePluginImage'
import {
    Destination,
    ImportApp,
    PipelineBackend,
    PluginBasedNode,
    SiteApp,
    Transformation,
    WebhookDestination,
} from './types'

const PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES_ARR = [
    // frontend apps
    'https://github.com/PostHog/bug-report-app',
    'https://github.com/PostHog/early-access-features-app',
    'https://github.com/PostHog/notification-bar-app',
    'https://github.com/PostHog/pineapple-mode-app',
    // filtering apps
    'https://github.com/PostHog/downsampling-plugin',
    'https://github.com/PostHog/posthog-filter-out-plugin',
    // transformation apps
    'https://github.com/PostHog/language-url-splitter-app',
    'https://github.com/PostHog/posthog-app-url-parameters-to-event-properties',
    'https://github.com/PostHog/posthog-plugin-geoip',
    'https://github.com/PostHog/posthog-url-normalizer-plugin',
    'https://github.com/PostHog/property-filter-plugin',
    'https://github.com/PostHog/semver-flattener-plugin',
    'https://github.com/PostHog/taxonomy-plugin',
    'https://github.com/PostHog/timestamp-parser-plugin',
    'https://github.com/PostHog/user-agent-plugin',
]
export const PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES = new Set(PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES_ARR)

const GLOBAL_EXPORT_PLUGINS = [
    // export apps
    'https://github.com/PostHog/customerio-plugin',
    'https://github.com/PostHog/hubspot-plugin',
    'https://github.com/PostHog/pace-posthog-integration',
    'https://github.com/PostHog/posthog-avo-plugin',
    'https://github.com/PostHog/posthog-engage-so-plugin',
    'https://github.com/PostHog/posthog-intercom-plugin',
    'https://github.com/PostHog/posthog-laudspeaker-app',
    'https://github.com/PostHog/posthog-patterns-app',
    'https://github.com/PostHog/posthog-twilio-plugin',
    'https://github.com/PostHog/posthog-variance-plugin',
    'https://github.com/PostHog/rudderstack-posthog-plugin',
    'https://github.com/PostHog/salesforce-plugin',
    'https://github.com/PostHog/sendgrid-plugin',
    'https://github.com/PostHog/posthog-loops-plugin',
]
export const GLOBAL_PLUGINS = new Set([...PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES_ARR, ...GLOBAL_EXPORT_PLUGINS])

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

export function nameColumn<
    T extends { stage: PipelineStage; id: number; name: string; description?: string }
>(): LemonTableColumn<T, 'name'> {
    return {
        title: 'Name',
        sticky: true,
        render: function RenderName(_, pipelineNode) {
            return (
                <LemonTableLink
                    to={urls.pipelineNode(pipelineNode.stage, pipelineNode.id, PipelineNodeTab.Configuration)}
                    title={
                        <>
                            <Tooltip title="Click to update configuration, view metrics, and more">
                                <span>{pipelineNode.name}</span>
                            </Tooltip>
                        </>
                    }
                    description={pipelineNode.description}
                />
            )
        },
    }
}
export function appColumn<T extends { plugin: Transformation['plugin'] }>(): LemonTableColumn<T, 'plugin'> {
    return {
        title: 'App',
        width: 0,
        render: function RenderAppInfo(_, pipelineNode) {
            return <RenderApp plugin={pipelineNode.plugin} />
        },
    }
}

function pluginMenuItems(node: PluginBasedNode): LemonMenuItem[] {
    if (node.plugin?.url) {
        return [
            {
                label: 'View app source code',
                to: node.plugin.url,
                targetBlank: true,
            },
        ]
    }
    return []
}

export function usePipelineNodeMenuCommonItems(
    node: Transformation | SiteApp | ImportApp | Destination
): LemonMenuItem[] {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { canConfigurePlugins } = useValues(pipelineAccessLogic)

    const items: LemonMenuItem[] = [
        {
            label: canConfigurePlugins ? 'Edit configuration' : 'View configuration',
            to:
                'hog_function' in node && node.hog_function
                    ? urls.hogFunction(node.hog_function.id)
                    : urls.pipelineNode(node.stage, node.id, PipelineNodeTab.Configuration),
        },
        {
            label: 'View metrics',
            // TODO: metrics URL
            to: urls.pipelineNode(node.stage, node.id, PipelineNodeTab.Metrics),
        },
        {
            label: 'View logs',
            // TODO: logs URL
            to: urls.pipelineNode(node.stage, node.id, PipelineNodeTab.Logs),
        },
    ]
    if (node.backend === PipelineBackend.Plugin) {
        items.concat(pluginMenuItems(node))
    }
    return items
}

export async function loadPluginsFromUrl(url: string): Promise<Record<number, PluginType>> {
    const results: PluginType[] = await api.loadPaginatedResults<PluginType>(url)
    return Object.fromEntries(results.map((plugin) => [plugin.id, plugin]))
}

export function usePipelinePluginBackedNodeMenuCommonItems(
    node: Transformation | SiteApp | ImportApp | WebhookDestination,
    toggleEnabled: any,
    loadPluginConfigs: any,
    inOverview?: boolean
): LemonMenuItem[] {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    const { canConfigurePlugins } = useValues(pipelineAccessLogic)

    return [
        {
            label: node.enabled ? 'Disable app' : 'Enable app',
            onClick: () =>
                toggleEnabled({
                    enabled: !node.enabled,
                    id: node.id,
                }),
            disabledReason: canConfigurePlugins ? undefined : 'You do not have permission to toggle.',
        },
        ...usePipelineNodeMenuCommonItems(node),
        ...(!inOverview
            ? [
                  {
                      label: 'Delete app',
                      status: 'danger' as const, // for typechecker happiness
                      onClick: () => {
                          void deleteWithUndo({
                              endpoint: `plugin_config`,
                              object: {
                                  id: node.id,
                                  name: node.name,
                              },
                              callback: loadPluginConfigs,
                          }).catch((e) => {
                              lemonToast.error(`Failed to delete plugin: ${e.detail}`)
                          })
                      },
                      disabledReason: canConfigurePlugins ? undefined : 'You do not have permission to delete.',
                  },
              ]
            : []),
    ]
}

export function checkPermissions(stage: PipelineStage, togglingToEnabledOrNew: boolean): boolean {
    if (stage === PipelineStage.ImportApp && togglingToEnabledOrNew) {
        lemonToast.error('Import apps are deprecated and cannot be enabled.')
        return false
    }
    return true
}
