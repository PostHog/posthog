import { urls } from 'scenes/urls'

import { HogFunctionTypeType, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

export function hogFunctionNewUrl(type: HogFunctionTypeType, template?: string): string {
    return type === 'email'
        ? urls.messagingProviderNew(template)
        : type === 'broadcast'
        ? urls.messagingBroadcastNew()
        : urls.pipelineNodeNew(hogFunctionTypeToPipelineStage(type), template ? `hog-${template}` : undefined)
}

export function hogFunctionUrl(type: HogFunctionTypeType | PipelineStage, id?: string): string {
    if (type === 'email') {
        return id ? urls.messagingProvider(id) : urls.messagingProviders()
    } else if (type === 'broadcast') {
        return id ? urls.messagingBroadcast(id) : urls.messagingBroadcasts()
    } else if (type === 'internal_destination') {
        // TODO: Fix this somehow
        return urls.errorTrackingAlerts()
    }
    return id
        ? urls.pipelineNode(
              hogFunctionTypeToPipelineStage(type),
              id.startsWith('hog-') ? id : `hog-${id}`,
              PipelineNodeTab.Configuration
          )
        : urls.pipeline(PipelineTab.Destinations)
}

// Supports both hog function types and pipeline stages themselves as input
export function hogFunctionTypeToPipelineStage(
    type: string
): PipelineStage.Destination | PipelineStage.Transformation | PipelineStage.SiteApp {
    switch (type) {
        case 'site_destination':
            return PipelineStage.Destination
        case 'site-destination':
            return PipelineStage.Destination
        case 'destination':
            return PipelineStage.Destination
        case 'site_app':
            return PipelineStage.SiteApp
        case 'site-app':
            return PipelineStage.SiteApp
        case 'transformation':
            return PipelineStage.Transformation
        default:
            return PipelineStage.Destination
    }
}
