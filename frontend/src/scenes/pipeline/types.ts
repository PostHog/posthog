import { BatchExportConfiguration, BatchExportService, PipelineStage, PluginType } from '~/types'

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

export type Destination = BatchExportDestination | WebhookDestination

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
