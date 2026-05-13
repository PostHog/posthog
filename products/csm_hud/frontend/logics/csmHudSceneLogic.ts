import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { AccountActivity, loadActivity } from '../queries/activity'
import { loadProjection } from '../queries/projection'
import type { ProjectionRow } from '../utils/projection'
import type { csmHudSceneLogicType } from './csmHudSceneLogicType'

export interface FleetRow {
    id: string
    externalId: string
    name: string
    healthScore: number | null
    mrr: number | null
    usersCount: number
    stripeCustomerId: string | null
    traits: Record<string, unknown>
    segments: unknown[]
    keyRoles: unknown[]
}

function fleetSql(csmEmail: string | null): { query: string; values?: Record<string, unknown> } {
    const base = `
SELECT
  id,
  external_id,
  name,
  toString(coalesce(health_score, 0)) AS health_score,
  toString(coalesce(mrr, 0)) AS mrr,
  toString(coalesce(users_count, 0)) AS users_count,
  traits,
  segments,
  key_roles
FROM vitally_accounts
WHERE key_roles LIKE '%"label":"CSM"%'
`.trim()
    if (!csmEmail) {
        // No CSM filter — return any account that has any CSM assignment.
        return { query: `${base}\nLIMIT 100` }
    }
    return {
        query: `${base}\n  AND key_roles LIKE {csmPattern}\nLIMIT 100`,
        values: { csmPattern: `%"email":"${csmEmail}"%` },
    }
}

function parseJson<T>(value: unknown, fallback: T): T {
    if (value == null) {
        return fallback
    }
    if (typeof value !== 'string') {
        return value as T
    }
    try {
        return JSON.parse(value) as T
    } catch {
        return fallback
    }
}

function toFloat(value: unknown): number | null {
    if (value == null || value === '') {
        return null
    }
    const n = typeof value === 'number' ? value : parseFloat(String(value))
    return Number.isFinite(n) ? n : null
}

function mapFleetRow(row: unknown[]): FleetRow {
    const [id, externalId, name, healthScore, mrr, usersCount, traits, segments, keyRoles] = row
    const parsedTraits = parseJson<Record<string, unknown>>(traits, {})
    const stripeId = parsedTraits['stripe.customerId']
    return {
        id: String(id ?? ''),
        externalId: String(externalId ?? ''),
        name: String(name ?? ''),
        healthScore: toFloat(healthScore),
        mrr: toFloat(mrr),
        usersCount: parseInt(String(usersCount ?? '0'), 10) || 0,
        stripeCustomerId: typeof stripeId === 'string' && stripeId.length > 0 ? stripeId : null,
        traits: parsedTraits,
        segments: parseJson<unknown[]>(segments, []),
        keyRoles: parseJson<unknown[]>(keyRoles, []),
    }
}

export const csmHudSceneLogic = kea<csmHudSceneLogicType>([
    path(['products', 'csm_hud', 'frontend', 'logics', 'csmHudSceneLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({
        setRenewalsPlanFilter: (filter: 'all' | 'annual') => ({ filter }),
        setCsmFilter: (email: string) => ({ email }),
    }),
    reducers({
        renewalsPlanFilter: ['annual' as 'all' | 'annual', { setRenewalsPlanFilter: (_, { filter }) => filter }],
        csmFilter: ['', { setCsmFilter: (_, { email }) => email }],
    }),
    selectors({
        // TODO restore before merge: gate behind FEATURE_FLAGS.SCENE_CSM_HUD + is_staff + @posthog.com
        canAccess: [() => [], (): boolean => true],
    }),
    loaders(({ values }) => ({
        fleet: [
            [] as FleetRow[],
            {
                loadFleet: async () => {
                    if (!values.canAccess) {
                        return []
                    }
                    const trimmed = values.csmFilter.trim()
                    const { query, values: queryValues } = fleetSql(trimmed === '' ? null : trimmed)
                    const node: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query,
                        tags: { productKey: 'internal', scene: 'CSMHud', name: 'csm_hud_fleet' },
                        ...(queryValues ? { values: queryValues } : {}),
                    }
                    const response = await api.query(node)
                    return (response.results ?? []).map(mapFleetRow)
                },
            },
        ],
        projection: [
            {} as Record<string, ProjectionRow>,
            {
                loadProjection: async (fleet: FleetRow[]) => {
                    if (fleet.length === 0) {
                        return {}
                    }
                    const orgIds: string[] = []
                    const nameByOrg: Record<string, string> = {}
                    const stripeByOrg: Record<string, string> = {}
                    for (const row of fleet) {
                        if (!row.externalId) {
                            continue
                        }
                        orgIds.push(row.externalId)
                        nameByOrg[row.externalId] = row.name
                        if (row.stripeCustomerId) {
                            stripeByOrg[row.externalId] = row.stripeCustomerId
                        }
                    }
                    return loadProjection({ orgIds, nameByOrg, stripeByOrg })
                },
            },
        ],
        activity: [
            {} as Record<string, AccountActivity>,
            {
                loadActivity: async (fleet: FleetRow[]) => {
                    if (fleet.length === 0) {
                        return {}
                    }
                    const accountIds: string[] = []
                    const zendeskByAccount: Record<string, number> = {}
                    for (const row of fleet) {
                        if (!row.externalId) {
                            continue
                        }
                        accountIds.push(row.externalId)
                        const raw = row.traits['zendesk.id']
                        const n = typeof raw === 'number' ? raw : parseInt(String(raw ?? ''), 10)
                        if (Number.isFinite(n) && n > 0) {
                            zendeskByAccount[row.externalId] = n
                        }
                    }
                    return loadActivity({ accountIds, zendeskByAccount })
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadFleetSuccess: ({ fleet }) => {
            if (fleet.length > 0) {
                actions.loadProjection(fleet)
                actions.loadActivity(fleet)
            }
        },
        setCsmFilter: () => {
            actions.loadFleet()
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.canAccess) {
            actions.loadFleet()
        }
    }),
])
