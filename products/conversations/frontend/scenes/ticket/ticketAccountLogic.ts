import { connect, events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { conversationsTicketsLinkedAccountRetrieve } from '../../generated/api'
import type { TicketLinkedAccountApi } from '../../generated/api.schemas'
import type { ticketAccountLogicType } from './ticketAccountLogicType'

export interface TicketAccountLogicProps {
    ticketId: string
}

export const ticketAccountLogic = kea<ticketAccountLogicType>([
    props({} as TicketAccountLogicProps),
    key((props) => props.ticketId),
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'ticketAccountLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    loaders(({ values, props }) => ({
        // Null when the ticket has no organization_id, no matching account, or the caller
        // lacks access — the endpoint returns null in all three cases and the panel hides.
        account: [
            null as TicketLinkedAccountApi | null,
            {
                loadAccount: async (): Promise<TicketLinkedAccountApi | null> => {
                    const response = await conversationsTicketsLinkedAccountRetrieve(
                        String(values.currentTeamId),
                        props.ticketId
                    )
                    return response.account
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadAccount,
    })),
])
