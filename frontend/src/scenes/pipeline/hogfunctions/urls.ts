import { urls } from 'scenes/urls'

import {
    HogFunctionTemplateWithSubTemplateType,
    HogFunctionType,
    HogFunctionTypeType,
    PipelineNodeTab,
    PipelineStage,
    PipelineTab,
} from '~/types'

export function getHogFunctionTemplateUrl(template: HogFunctionTemplateWithSubTemplateType): string {
    return template.type === 'broadcast'
        ? urls.messagingBroadcastNew()
        : template.type === 'internal_destination' && template.sub_template_id?.includes('error-tracking')
        ? urls.errorTrackingAlert(template.id)
        : urls.pipelineNodeNew(hogFunctionTypeToPipelineStage(template.type), {
              id: template.id,
          })
}

export function getHogFunctionUrl(hogFunction: HogFunctionType): string {
    if (hogFunction.type === 'broadcast') {
        return urls.messagingBroadcast(hogFunction.id)
    } else if (hogFunction.kind === 'messaging_campaign') {
        return urls.messagingCampaign(hogFunction.id)
    } else if (hogFunction.type === 'internal_destination' && hogFunction.template?.id?.includes('error-tracking')) {
        return urls.errorTrackingAlert(hogFunction.id)
    }
    return urls.pipelineNode(
        hogFunctionTypeToPipelineStage(hogFunction.type),
        hogFunction.id.startsWith('hog-') ? hogFunction.id : `hog-${hogFunction.id}`,
        PipelineNodeTab.Configuration
    )
}

// TODO: We will replace this with a new HogFunctionScene
export function hogFunctionUrl(type: HogFunctionTypeType | PipelineStage, id?: string): string {
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
