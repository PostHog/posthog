import { PipelineStage } from '~/types'

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
