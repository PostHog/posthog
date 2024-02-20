import {
    BatchExportConfiguration,
    BatchExportDestination as BatchExportService,
    PipelineStage,
    PluginConfigWithPluginInfoNew,
    PluginType,
} from '~/types'

export enum PipelineBackend {
    BatchExport = 'batch_export',
    Plugin = 'plugin',
}

// Base - we're taking a discriminated union approach here, so that TypeScript can discern types for free

interface PipelineNodeBase {
    name: string
    description?: string
    enabled: boolean
    updated_at: string
    created_at: string
}

// Split by backend

export interface PluginBasedStepBase extends PipelineNodeBase {
    backend: PipelineBackend.Plugin
    id: number
    plugin: PluginType
    config: Record<string, any>
}
/** NOTE: Batch exports are only used in Destinations, but we're making this a bit more abstract for clearer types. */
export interface BatchExportBasedStep extends PipelineNodeBase {
    backend: PipelineBackend.BatchExport
    /** UUID */
    id: string
    service: BatchExportService
    interval: BatchExportConfiguration['interval']
}

// Stage: Filters

export interface Filter extends PluginBasedStepBase {
    stage: PipelineStage.Filter
}

// Stage: Transformations

export interface Transformation extends PluginBasedStepBase {
    stage: PipelineStage.Transformation
    order: number
}

// Stage: Destinations

export interface WebhookDestination extends PluginBasedStepBase {
    stage: PipelineStage.Destination
    interval: 'realtime'
}
export interface BatchExportDestination extends BatchExportBasedStep {
    stage: PipelineStage.Destination
}
export type Destination = BatchExportDestination | WebhookDestination

// Legacy: Site apps
export interface SiteApp extends PluginBasedStepBase {
    stage: PipelineStage.SiteApp
}

// Legacy: Import apps
export interface ImportApp extends PluginBasedStepBase {
    stage: PipelineStage.ImportApp
}

// Final

export type PipelineNode = Filter | Transformation | Destination | SiteApp | ImportApp

// Utils

function isPluginConfig(
    candidate: PluginConfigWithPluginInfoNew | BatchExportConfiguration
): candidate is PluginConfigWithPluginInfoNew {
    return 'plugin' in candidate
}

export function convertToPipelineNode<S extends PipelineStage>(
    candidate: PluginConfigWithPluginInfoNew | BatchExportConfiguration,
    stage: S
): S extends PipelineStage.Filter
    ? Filter
    : S extends PipelineStage.Transformation
    ? Transformation
    : S extends PipelineStage.Destination
    ? Destination
    : S extends PipelineStage.SiteApp
    ? SiteApp
    : S extends PipelineStage.ImportApp
    ? ImportApp
    : never {
    let node: PipelineNode
    if (isPluginConfig(candidate)) {
        const almostNode: Omit<
            Filter | Transformation | WebhookDestination | SiteApp | ImportApp,
            'frequency' | 'order'
        > = {
            stage: stage,
            backend: PipelineBackend.Plugin,
            id: candidate.id,
            name: candidate.name,
            description: candidate.description,
            enabled: candidate.enabled,
            created_at: candidate.updated_at, // TODO: Add created_at to plugin configs in the backend
            updated_at: candidate.updated_at,
            config: candidate.config,
            plugin: candidate.plugin_info,
        }
        if (stage === PipelineStage.Transformation) {
            node = {
                ...almostNode,
                stage,
                order: candidate.order,
            }
        } else if (stage === PipelineStage.Destination) {
            node = {
                ...almostNode,
                stage,
                interval: 'realtime',
            }
        } else if (stage === PipelineStage.SiteApp || stage === PipelineStage.ImportApp) {
            node = {
                ...almostNode,
                stage,
            }
        } else {
            node = almostNode as Filter
        }
    } else {
        node = {
            stage: stage as PipelineStage.Destination,
            backend: PipelineBackend.BatchExport,
            interval: candidate.interval,
            id: candidate.id,
            name: candidate.name,
            description: `${candidate.destination.type} batch export`, // TODO: add to backend
            enabled: !candidate.paused,
            created_at: candidate.created_at,
            updated_at: candidate.created_at, // TODO: Add updated_at to batch exports in the backend
            service: candidate.destination,
        }
    }
    return node as any
}
