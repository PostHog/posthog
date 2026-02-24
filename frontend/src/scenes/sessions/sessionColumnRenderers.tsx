import { SessionDisplay } from 'scenes/sessions/SessionDisplay'

import { QueryContextColumn } from '~/queries/types'

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
