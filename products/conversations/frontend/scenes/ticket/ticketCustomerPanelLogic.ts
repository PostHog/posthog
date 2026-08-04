import { actions, connect, events, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { conversationsTicketsLinkedAccountRetrieve } from '../../generated/api'
import type { TicketLinkedAccountApi } from '../../generated/api.schemas'
import type { ticketCustomerPanelLogicType } from './ticketCustomerPanelLogicType'

export type TicketCustomerTab = 'account' | 'related'

export interface TicketCustomerPanelLogicProps {
    ticketId: string
    // Whether to attempt loading the linked customer analytics account (feature flag + organization
    // gating is done by the caller). When false we skip the request and the account tab never appears.
    accountEnabled?: boolean
}

export const ticketCustomerPanelLogic = kea<ticketCustomerPanelLogicType>([
    props({} as TicketCustomerPanelLogicProps),
    key((props) => props.ticketId),
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'ticketCustomerPanelLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setActiveTab: (tab: TicketCustomerTab) => ({ tab }),
        setPanelOpen: (open: boolean) => ({ open }),
    }),
    loaders(({ values, props }) => ({
        // Null when the account is disabled for this ticket, the ticket has no organization_id, no
        // matching account, or the caller lacks access — in every case the account tab hides.
        account: [
            null as TicketLinkedAccountApi | null,
            {
                loadAccount: async (): Promise<TicketLinkedAccountApi | null> => {
                    if (props.accountEnabled === false) {
                        return null
                    }
                    const response = await conversationsTicketsLinkedAccountRetrieve(
                        String(values.currentTeamId),
                        props.ticketId
                    )
                    return response.account
                },
            },
        ],
    })),
    reducers({
        // Null until the user manually switches tabs — until then we follow the preferred default
        // (the account when it exists) resolved by the activeTab selector.
        activeTabOverride: [
            null as TicketCustomerTab | null,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        // Open by default. Picking a tab also opens the panel, so switching tabs while collapsed
        // reveals the chosen one.
        panelOpen: [
            true,
            {
                setPanelOpen: (_, { open }) => open,
                setActiveTab: () => true,
            },
        ],
    }),
    selectors({
        activeTab: [
            (s) => [s.activeTabOverride, s.account],
            (override, account): TicketCustomerTab => override ?? (account ? 'account' : 'related'),
        ],
    }),
    events(({ actions, props }) => ({
        afterMount: () => {
            if (props.accountEnabled !== false) {
                actions.loadAccount()
            }
        },
    })),
])
