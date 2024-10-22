import { urls } from 'scenes/urls'

import { HogFunctionTypeType, PipelineNodeTab, PipelineStage, PipelineTab } from '~/types'

export function hogFunctionNewUrl(type: HogFunctionTypeType, template?: string): string {
    return type === 'email'
        ? urls.messagingProviderNew(template)
        : type === 'broadcast'
        ? urls.messagingBroadcastNew()
        : urls.pipelineNodeNew(PipelineStage.Destination, template ? `hog-${template}` : undefined)
}

export function hogFunctionUrl(type: HogFunctionTypeType, id?: string): string {
    if (type === 'email') {
        return id ? urls.messagingProvider(id) : urls.messagingProviders()
    } else if (type === 'broadcast') {
        return id ? urls.messagingBroadcast(id) : urls.messagingBroadcasts()
    }
    return id
        ? urls.pipelineNode(PipelineStage.Destination, `hog-${id}`, PipelineNodeTab.Configuration)
        : urls.pipeline(PipelineTab.Destinations)
}
