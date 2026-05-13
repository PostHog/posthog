import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { Note, queryNotes, queryTasks, queryTickets, queryTopUsers, Task, Ticket, TopUser } from '../queries/customer'
import { csmHudSceneLogic, FleetRow } from './csmHudSceneLogic'
import type { customerDetailLogicType } from './customerDetailLogicType'

export interface CustomerDetailLogicProps {
    externalId: string
}

function zendeskIdFromTraits(traits: Record<string, unknown>): number | null {
    const raw = traits['zendesk.id']
    if (raw == null) {
        return null
    }
    const n = typeof raw === 'number' ? raw : parseInt(String(raw), 10)
    return Number.isFinite(n) && n > 0 ? n : null
}

export const customerDetailLogic = kea<customerDetailLogicType>([
    path((key) => ['products', 'csm_hud', 'frontend', 'logics', 'customerDetailLogic', key ?? 'unknown']),
    props({} as CustomerDetailLogicProps),
    key((props) => props.externalId || 'unknown'),
    connect(() => ({
        values: [csmHudSceneLogic, ['fleet', 'fleetLoading', 'projection', 'projectionLoading']],
        actions: [csmHudSceneLogic, ['loadFleet', 'loadFleetSuccess']],
    })),
    selectors({
        account: [
            (s, p) => [s.fleet, p.externalId],
            (fleet: FleetRow[], externalId: string): FleetRow | null =>
                fleet.find((row) => row.externalId === externalId) ?? null,
        ],
        accountProjection: [
            (s, p) => [s.projection, p.externalId],
            (projection, externalId: string) => projection[externalId] ?? null,
        ],
        zendeskOrgId: [
            (s) => [s.account],
            (account: FleetRow | null): number | null => (account ? zendeskIdFromTraits(account.traits) : null),
        ],
    }),
    loaders(({ props, values }) => ({
        topUsers: [
            [] as TopUser[],
            {
                loadTopUsers: () => queryTopUsers(props.externalId),
            },
        ],
        tickets: [
            [] as Ticket[],
            {
                loadTickets: () => queryTickets(values.zendeskOrgId),
            },
        ],
        notes: [
            [] as Note[],
            {
                loadNotes: () => queryNotes(props.externalId),
            },
        ],
        tasks: [
            [] as Task[],
            {
                loadTasks: () => queryTasks(props.externalId),
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        // Tickets need zendeskOrgId, which only resolves after the fleet load
        // completes. Refire once the fleet arrives.
        loadFleetSuccess: () => {
            if (values.zendeskOrgId) {
                actions.loadTickets()
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // Fleet is the source of name + zendeskOrgId. Trigger a load if the
        // parent scene logic hasn't already done so (e.g. direct URL hit).
        if (values.fleet.length === 0 && !values.fleetLoading) {
            actions.loadFleet()
        }
        actions.loadTopUsers()
        actions.loadNotes()
        actions.loadTasks()
        if (values.zendeskOrgId) {
            actions.loadTickets()
        }
    }),
])
