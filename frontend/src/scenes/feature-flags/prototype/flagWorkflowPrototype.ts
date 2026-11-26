import { PROTOTYPE_SOURCES } from 'scenes/messaging-cta-prototype/messagingCtaPrototype'

// PROTOTYPE, throwaway: variant A's handoff, a workflow triggered when a person is first served this flag.
import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    captureMessageAudienceClicked,
    messageAudienceUrl,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { draftMessage } from 'products/workflows/frontend/MessageAudience/messageDrafts'

export function createFlagWorkflowUrlForPrototype(flag: Pick<FeatureFlagType, 'id' | 'key' | 'name'>): string {
    captureMessageAudienceClicked(PROTOTYPE_SOURCES.create, 'workflow')
    const featureName = flag.name || flag.key
    return messageAudienceUrl(
        {
            source: PROTOTYPE_SOURCES.create,
            sourceRecord: `feature_flag:${flag.id}`,
            properties: [],
            workflowEmail: draftMessage({ kind: 'feature_available', featureName }),
            workflowTrigger: {
                type: 'event',
                filters: {
                    events: [
                        {
                            id: '$feature_flag_called',
                            name: '$feature_flag_called',
                            type: 'events',
                            order: 0,
                            properties: [
                                {
                                    key: '$feature_flag',
                                    value: [flag.key],
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Event,
                                },
                                {
                                    key: '$feature_flag_response',
                                    value: ['false'],
                                    operator: PropertyOperator.IsNot,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                },
            },
        },
        'workflow'
    )
}
