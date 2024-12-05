import {
    messagingBroadcast,
    messagingBroadcastNew,
    messagingBroadcasts,
    messagingProvider,
    messagingProviderNew,
    messagingProviders,
} from 'products/messaging/frontend/urls'
import { urls } from 'scenes/urls'

import { HogFunctionTypeType, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

export function hogFunctionNewUrl(type: HogFunctionTypeType, template?: string): string {
    return type === 'email'
        ? messagingProviderNew(template)
        : type === 'broadcast'
        ? messagingBroadcastNew()
        : urls.pipelineNodeNew(hogFunctionTypeToPipelineStage(type), template ? `hog-${template}` : undefined)
}

export function hogFunctionUrl(type: HogFunctionTypeType | PipelineStage, id?: string): string {
    if (type === 'email') {
        return id ? messagingProvider(id) : messagingProviders()
    } else if (type === 'broadcast') {
        return id ? messagingBroadcast(id) : messagingBroadcasts()
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
export function hogFunctionTypeToPipelineStage(type: string): PipelineStage {
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
        default:
            return PipelineStage.Destination
    }
}
