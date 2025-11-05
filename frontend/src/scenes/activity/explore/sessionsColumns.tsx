import { TZLabel } from 'lib/components/TZLabel'
import { colonDelimitedDuration } from 'lib/utils'

import { QueryContext } from '~/queries/types'

export function getSessionsColumns(): QueryContext['columns'] {
    return {
        session_id: {
            title: 'Session ID',
        },
        $start_timestamp: {
            title: 'Start time',
            render: ({ value }) => <TZLabel time={value as string} showSeconds />,
        },
        $end_timestamp: {
            title: 'End time',
            render: ({ value }) => <TZLabel time={value as string} showSeconds />,
        },
        $session_duration: {
            title: 'Duration',
            render: ({ value }) => <>{colonDelimitedDuration(value as number)}</>,
        },
        $entry_current_url: {
            title: 'Entry URL',
        },
        $pageview_count: {
            title: 'Pageviews',
        },
        $is_bounce: {
            title: 'Bounced',
            render: ({ value }) => <>{value === 1 || value === true ? 'Yes' : 'No'}</>,
        },
    }
}
