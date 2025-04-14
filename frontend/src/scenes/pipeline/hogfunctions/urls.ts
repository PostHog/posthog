import { urls } from 'scenes/urls'

import { HogFunctionKind, HogFunctionTypeType, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

export function hogFunctionNewUrl(type: HogFunctionTypeType, template?: string): string {
    return type === 'broadcast'
        ? urls.messagingBroadcastNew()
        : type === 'internal_destination' && template?.includes('error-tracking')
        ? urls.errorTrackingAlert(template)
        : type === 'internal_destination' && template?.includes('insight-alert-firing')
        ? urls.insightAlertDestination(template)
        : urls.pipelineNodeNew(hogFunctionTypeToPipelineStage(type), template ? `hog-${template}` : undefined)
}

export function hogFunctionUrl(
    type: HogFunctionTypeType | PipelineStage,
    id?: string,
    template?: string,
    kind?: HogFunctionKind
): string {
    if (type === 'broadcast') {
        return id ? urls.messagingBroadcast(id) : urls.messagingBroadcasts()
    } else if (kind === 'messaging_campaign') {
        return id ? urls.messagingCampaign(id) : urls.messagingCampaigns()
    } else if (type === 'internal_destination' && template?.includes('error-tracking')) {
        return id ? urls.errorTrackingAlert(id) : urls.errorTrackingConfiguration()
    } else if (type === 'internal_destination' && template?.includes('insight-alert-firing')) {
        return id ? urls.insightAlertDestination(id) : urls.insights()
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
