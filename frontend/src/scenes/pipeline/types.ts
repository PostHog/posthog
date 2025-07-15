import {
    BatchExportConfiguration,
    BatchExportService,
    HogFunctionType,
    PipelineStage,
    PluginConfigWithPluginInfoNew,
    PluginType,
} from '~/types'

export enum PipelineBackend {
    BatchExport = 'batch_export',
    Plugin = 'plugin',
    HogFunction = 'hog_function',
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

export interface PluginBasedNode extends PipelineNodeBase {
    backend: PipelineBackend.Plugin
    id: number
    plugin: PluginType
    config: Record<string, any>
}

/** NOTE: Batch exports are only used in Destinations, but we're making this a bit more abstract for clearer types. */
export interface BatchExportBasedNode extends PipelineNodeBase {
    backend: PipelineBackend.BatchExport
    /** UUID */
    id: string
    service: BatchExportService
    interval: BatchExportConfiguration['interval']
}

export interface HogFunctionBasedNode extends PipelineNodeBase {
    backend: PipelineBackend.HogFunction
    id: string
    hog_function: HogFunctionType
}

// Stage: Transformations

export interface Transformation extends PluginBasedNode {
    stage: PipelineStage.Transformation
    order: number
}

// Stage: Destinations

export interface WebhookDestination extends PluginBasedNode {
    stage: PipelineStage.Destination
    interval: 'realtime'
}
export interface BatchExportDestination extends BatchExportBasedNode {
    stage: PipelineStage.Destination
}
export interface FunctionDestination extends HogFunctionBasedNode {
    stage: PipelineStage.Destination
    interval: 'realtime'
}
export type Destination = BatchExportDestination | WebhookDestination | FunctionDestination

export type NewDestinationItemType = {
    icon: JSX.Element
    url: string
    name: string
    description: string
    backend: PipelineBackend
    free: boolean
    status?: 'stable' | 'alpha' | 'beta' | 'deprecated' | 'coming_soon' | 'hidden'
}

export type NewDestinationFilters = {
    search?: string
    kind?: PipelineBackend
}

export interface SiteApp extends PluginBasedNode {
    stage: PipelineStage.SiteApp
}

// Legacy: Import apps
export interface ImportApp extends PluginBasedNode {
    stage: PipelineStage.ImportApp
}

export interface Source extends PluginBasedNode {
    stage: PipelineStage.Source
}

// Final

export type PipelineNode = Transformation | Destination | SiteApp | ImportApp | Source

// Utils

function isPluginConfig(
    candidate: PluginConfigWithPluginInfoNew | BatchExportConfiguration
): candidate is PluginConfigWithPluginInfoNew {
    return 'plugin' in candidate
}

export function convertToPipelineNode<S extends PipelineStage>(
    candidate: PluginConfigWithPluginInfoNew | BatchExportConfiguration | HogFunctionType,
    stage: S
): S extends PipelineStage.Transformation
    ? Transformation
    : S extends PipelineStage.Destination
    ? Destination
    : S extends PipelineStage.SiteApp
    ? SiteApp
    : S extends PipelineStage.ImportApp
    ? ImportApp
    : S extends PipelineStage.Source
    ? Source
    : never {
    let node: PipelineNode

    // check if type is a hog function
    if ('hog' in candidate) {
        node = {
            stage: stage as PipelineStage.Destination,
            backend: PipelineBackend.HogFunction,
            interval: 'realtime',
            id: `hog-${candidate.id}`,
            name: candidate.name,
            description: candidate.description,
            enabled: candidate.enabled,
            created_at: candidate.created_at,
            updated_at: candidate.updated_at,
            hog_function: candidate,
        }
    } else if (isPluginConfig(candidate)) {
        const almostNode: Omit<
            Transformation | WebhookDestination | SiteApp | ImportApp | Source,
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
        } else {
            node = {
                ...almostNode,
                stage,
            }
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
