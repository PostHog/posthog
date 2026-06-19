import { IconArchive } from '@posthog/icons'

import { INBOX_FLAT_TAB_LIST_PARAMS } from '../../logics/reportListLogic'
import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'

/**
 * Reports the user dismissed (status `suppressed`). Same flat-list primitive as the other
 * report tabs – only the filter differs. Each card offers a Restore action that re-promotes
 * the report back into the inbox.
 */
export function ArchivedTab(): JSX.Element {
    return (
        <InboxReportList
            tabKey="archived"
            listParams={INBOX_FLAT_TAB_LIST_PARAMS.archived}
            Card={ReportCard}
            emptyState={{
                icon: <IconArchive className="text-2xl" />,
                title: 'Nothing archived',
                description: 'Reports you archive land here, where you can review them or restore them to the inbox.',
            }}
        />
    )
}
