import { QuillScenesTabs } from '../../components/ScenesTabs/QuillScenesTabs'
import { QuillSupportTicketsBanner } from '../../components/SupportTicketsBanner/QuillSupportTicketsBanner'
import { QuillTicketAppliedFilters } from '../../components/TicketAppliedFilters/QuillTicketAppliedFilters'
import { QuillTicketListBulkActions } from '../../components/TicketListBulkActions/QuillTicketListBulkActions'
import { QuillTicketListFilters } from '../../components/TicketListFilters/QuillTicketListFilters'
import { QuillSupportTicketsTable } from './QuillSupportTicketsTable'

/** The tickets scene below its title, on quill. */
export function QuillSupportTicketsSceneContent({ aiEnabled }: { aiEnabled: boolean }): JSX.Element {
    return (
        <div data-quill className="flex min-w-0 flex-col gap-3">
            <QuillSupportTicketsBanner aiEnabled={aiEnabled} />
            <QuillScenesTabs />
            <QuillTicketListFilters />
            <QuillTicketAppliedFilters />
            <QuillSupportTicketsTable />
            <QuillTicketListBulkActions />
        </div>
    )
}
