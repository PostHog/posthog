import { LemonMenuItem, LemonSkeleton, LemonTableColumn } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import api from 'lib/api'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import posthog from 'posthog-js'
import BigQueryIcon from 'public/pipeline/BigQuery.png'
import PostgresIcon from 'public/pipeline/Postgres.png'
import RedshiftIcon from 'public/pipeline/Redshift.svg'
import S3Icon from 'public/pipeline/S3.png'
import SnowflakeIcon from 'public/pipeline/Snowflake.png'
import { PluginImage, PluginImageSize } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

import {
    BatchExportConfiguration,
    BatchExportDestination,
    PipelineNodeTab,
    PipelineStage,
    PluginConfigTypeNew,
    PluginLogEntryType,
    PluginType,
} from '~/types'

import { PipelineLogLevel } from './pipelineNodeLogsLogic'
import { pipelineTransformationsLogic } from './transformationsLogic'
import {
    Destination,
    ImportApp,
    PipelineBackend,
    PluginBasedStepBase,
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
    'https://github.com/PostHog/schema-enforcer-plugin',
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
export const PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES = new Set([...PLUGINS_ALLOWED_WITHOUT_DATA_PIPELINES_ARR])

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
    'https://github.com/posthog/posthog-plugin-replicator',
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
                    <span>
                        <PluginImage plugin={plugin} size={imageSize} />
                    </span>
                )}
            </Tooltip>
        </div>
    )
}

export function RenderBatchExportIcon({ type }: { type: BatchExportDestination['type'] }): JSX.Element {
    const icon = {
        BigQuery: BigQueryIcon,
        Postgres: PostgresIcon,
        Redshift: RedshiftIcon,
        S3: S3Icon,
        Snowflake: SnowflakeIcon,
    }[type]

    return (
        <div className="flex items-center gap-4">
            <Link to={`https://posthog.com/docs/cdp/batch-exports/${type.toLowerCase()}`} target="_blank">
                <img src={icon} alt={type} height={60} width={60} />
            </Link>
        </div>
    )
}

export const logLevelToTypeFilter = (level: PipelineLogLevel): PluginLogEntryType => {
    switch (level) {
        case PipelineLogLevel.Debug:
            return PluginLogEntryType.Debug
        case PipelineLogLevel.Error:
            return PluginLogEntryType.Error
        case PipelineLogLevel.Info:
            return PluginLogEntryType.Info
        case PipelineLogLevel.Log:
            return PluginLogEntryType.Log
        case PipelineLogLevel.Warning:
            return PluginLogEntryType.Warn
        default:
            throw new Error('unknown log level')
    }
}

export const logLevelsToTypeFilters = (levels: PipelineLogLevel[]): PluginLogEntryType[] =>
    levels.map((l) => logLevelToTypeFilter(l))

export const typeToLogLevel = (type: PluginLogEntryType): PipelineLogLevel => {
    switch (type) {
        case PluginLogEntryType.Debug:
            return PipelineLogLevel.Debug
        case PluginLogEntryType.Error:
            return PipelineLogLevel.Error
        case PluginLogEntryType.Info:
            return PipelineLogLevel.Info
        case PluginLogEntryType.Log:
            return PipelineLogLevel.Log
        case PluginLogEntryType.Warn:
            return PipelineLogLevel.Warning
        default:
            throw new Error('unknown log type')
    }
}

export function LogLevelDisplay(level: PipelineLogLevel): JSX.Element {
    let color: string | undefined
    switch (level) {
        case PipelineLogLevel.Debug:
            color = 'text-muted'
            break
        case PipelineLogLevel.Log:
            color = 'text-default'
            break
        case PipelineLogLevel.Info:
            color = 'text-primary'
            break
        case PipelineLogLevel.Warning:
            color = 'text-warning'
            break
        case PipelineLogLevel.Error:
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

export const humanFriendlyFrequencyName = (frequency: Destination['interval']): string => {
    switch (frequency) {
        case 'realtime':
            return 'Realtime'
        case 'day':
            return 'Daily'
        case 'hour':
            return 'Hourly'
        case 'every 5 minutes':
            return '5 min'
    }
}

export function nameColumn<
    T extends { stage: PipelineStage; id: number; name: string; description?: string }
>(): LemonTableColumn<T, 'name'> {
    return {
        title: 'Name',
        sticky: true,
        render: function RenderName(_, pipelineNode) {
            return (
                <>
                    <Tooltip title="Click to update configuration, view metrics, and more">
                        <Link
                            to={urls.pipelineNode(pipelineNode.stage, pipelineNode.id, PipelineNodeTab.Configuration)}
                        >
                            <span className="row-name">{pipelineNode.name}</span>
                        </Link>
                    </Tooltip>
                    {pipelineNode.description && (
                        <LemonMarkdown className="row-description" lowKeyHeadings>
                            {pipelineNode.description}
                        </LemonMarkdown>
                    )}
                </>
            )
        },
    }
}
export function appColumn<T extends { plugin: Transformation['plugin'] }>(): LemonTableColumn<T, 'plugin'> {
    return {
        title: 'App',
        render: function RenderAppInfo(_, pipelineNode) {
            return <RenderApp plugin={pipelineNode.plugin} />
        },
    }
}

function pluginMenuItems(node: PluginBasedStepBase): LemonMenuItem[] {
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

export function pipelineNodeMenuCommonItems(node: Transformation | SiteApp | ImportApp | Destination): LemonMenuItem[] {
    const { canConfigurePlugins } = useValues(pipelineTransformationsLogic)

    const items: LemonMenuItem[] = [
        {
            label: canConfigurePlugins ? 'Edit configuration' : 'View configuration',
            to: urls.pipelineNode(node.stage, node.id, PipelineNodeTab.Configuration),
        },
        {
            label: 'View metrics',
            to: urls.pipelineNode(node.stage, node.id, PipelineNodeTab.Metrics),
        },
        {
            label: 'View logs',
            to: urls.pipelineNode(node.stage, node.id, PipelineNodeTab.Logs),
        },
    ]
    if (node.backend === PipelineBackend.Plugin) {
        items.concat(pluginMenuItems(node))
    }
    return items
}

export function pipelinePluginBackedNodeMenuCommonItems(
    node: Transformation | SiteApp | ImportApp | WebhookDestination,
    toggleEnabled: any,
    loadPluginConfigs: any,
    inOverview?: boolean
): LemonMenuItem[] {
    const { canConfigurePlugins } = useValues(pipelineTransformationsLogic)

    return [
        ...(!inOverview
            ? [
                  {
                      label: node.enabled ? 'Disable app' : 'Enable app',
                      onClick: () =>
                          toggleEnabled({
                              enabled: !node.enabled,
                              id: node.id,
                          }),
                      disabledReason: canConfigurePlugins
                          ? undefined
                          : 'You do not have permission to enable/disable apps.',
                  },
              ]
            : []),
        ...pipelineNodeMenuCommonItems(node),
        ...(!inOverview
            ? [
                  {
                      label: 'Delete app',
                      onClick: () => {
                          void deleteWithUndo({
                              endpoint: `plugin_config`,
                              object: {
                                  id: node.id,
                                  name: node.name,
                              },
                              callback: loadPluginConfigs,
                          })
                      },
                      disabledReason: canConfigurePlugins ? undefined : 'You do not have permission to delete apps.',
                  },
              ]
            : []),
    ]
}
