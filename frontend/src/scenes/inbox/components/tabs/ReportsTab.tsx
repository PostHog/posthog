import { IconNotebook } from '@posthog/icons'

import { INBOX_FLAT_TAB_LIST_PARAMS } from '../../logics/reportListLogic'
import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'

export function ReportsTab(): JSX.Element {
    return (
        <InboxReportList
            tabKey="reports"
            listParams={INBOX_FLAT_TAB_LIST_PARAMS.reports}
            Card={ReportCard}
            emptyState={{
                icon: <IconNotebook className="text-2xl" />,
                title: 'No reports yet',
                description:
                    "Reports are what agents surface when there's something worth your judgment but no clean code change to draft.",
            }}
        />
    )
}
