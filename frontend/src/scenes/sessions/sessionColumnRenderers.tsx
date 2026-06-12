import { QueryContextColumn } from '@posthog/query-frontend/types'

import { SessionDisplay } from 'scenes/sessions/SessionDisplay'

export const sessionColumnRenderers: Record<string, QueryContextColumn> = {
    'properties.$session_id': {
        title: 'Session',
        render: ({ value }) => {
            if (!value || typeof value !== 'string') {
                return null
            }
            return <SessionDisplay sessionId={value} />
        },
    },
}
