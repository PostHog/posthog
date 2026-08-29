import { MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { TicketAssignee } from 'products/conversations/frontend/components/Assignee'
import { conversationsTicketsPartialUpdate } from 'products/conversations/frontend/generated/api'

export interface ConversationsWidgetLogicProps {
    tileId: number
    onRefreshData?: () => void
}

export interface conversationsWidgetLogicValues {
    ticketAssignmentLoadingId: string | null
}

export interface conversationsWidgetLogicActions {
    assignTicket: (ticketId: string, assignee: TicketAssignee) => { assignee: TicketAssignee; ticketId: string }
    assignTicketFailure: (ticketId: string) => { ticketId: string }
    assignTicketLoading: (ticketId: string) => { ticketId: string }
    assignTicketSuccess: (ticketId: string) => { ticketId: string }
}

export type conversationsWidgetLogicType = MakeLogicType<
    conversationsWidgetLogicValues,
    conversationsWidgetLogicActions,
    ConversationsWidgetLogicProps
>

export const conversationsWidgetLogic = kea<conversationsWidgetLogicType>([
    props({} as ConversationsWidgetLogicProps),
    key((props) => props.tileId),
    path((key) => ['products', 'dashboards', 'widgets', 'conversations', 'conversationsWidgetLogic', key]),
    actions({
        assignTicket: (ticketId: string, assignee: TicketAssignee) => ({ ticketId, assignee }),
        assignTicketLoading: (ticketId: string) => ({ ticketId }),
        assignTicketSuccess: (ticketId: string) => ({ ticketId }),
        assignTicketFailure: (ticketId: string) => ({ ticketId }),
    }),
    reducers({
        ticketAssignmentLoadingId: [
            null as string | null,
            {
                assignTicketLoading: (_, { ticketId }) => ticketId,
                assignTicketSuccess: () => null,
                assignTicketFailure: () => null,
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        assignTicket: async ({ ticketId, assignee }) => {
            if (values.ticketAssignmentLoadingId) {
                return
            }
            actions.assignTicketLoading(ticketId)
            try {
                await conversationsTicketsPartialUpdate(String(getCurrentTeamId()), ticketId, { assignee })
                actions.assignTicketSuccess(ticketId)
                props.onRefreshData?.()
            } catch {
                actions.assignTicketFailure(ticketId)
                lemonToast.error('Could not update the assignee. Try again.')
            }
        },
    })),
])
