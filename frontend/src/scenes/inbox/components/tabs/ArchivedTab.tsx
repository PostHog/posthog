import { IconArchive } from '@posthog/icons'

import { INBOX_FLAT_TAB_LIST_PARAMS } from '../../logics/reportListLogic'
import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'

/**
 * Terminal reports: ones the user dismissed (status `suppressed`, restorable via a Restore action)
 * and ones resolved by a merged implementation PR (status `resolved`, shown for reference only).
 * Same flat-list primitive as the other report tabs – only the filter differs.
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
                description:
                    'Reports you archive land here, where you can restore them to the inbox. Resolved reports also appear here for reference.',
            }}
        />
    )
}
