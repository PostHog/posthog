import { actions, kea, path, reducers } from 'kea'

import { buildAiObservabilityStorageConfig } from '../../preferenceStorage'
import type { traceTimelineLogicType } from './traceTimelineLogicType'

export const traceTimelineLogic = kea<traceTimelineLogicType>([
    path(['products', 'ai_observability', 'frontend', 'components', 'TraceTimeline', 'traceTimelineLogic']),
    actions({
        setCollapsed: (collapsed: boolean) => ({ collapsed }),
    }),
    reducers({
        // Persisted per team so a user's choice to hide the timeline sticks across every trace.
        collapsed: [
            false,
            buildAiObservabilityStorageConfig('trace.timeline.collapsed'),
            {
                setCollapsed: (_, { collapsed }) => collapsed,
            },
        ],
    }),
])
