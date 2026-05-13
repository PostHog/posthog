import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { csmHudSceneLogicType } from './csmHudSceneLogicType'

export interface FleetRow {
    id: string
    externalId: string
    name: string
    healthScore: number | null
    mrr: number | null
    usersCount: number
    traits: Record<string, unknown>
    segments: unknown[]
    keyRoles: unknown[]
}

const FLEET_SQL = `
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
  AND key_roles LIKE {csmPattern}
LIMIT 100
`.trim()

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
    return {
        id: String(id ?? ''),
        externalId: String(externalId ?? ''),
        name: String(name ?? ''),
        healthScore: toFloat(healthScore),
        mrr: toFloat(mrr),
        usersCount: parseInt(String(usersCount ?? '0'), 10) || 0,
        traits: parseJson<Record<string, unknown>>(traits, {}),
        segments: parseJson<unknown[]>(segments, []),
        keyRoles: parseJson<unknown[]>(keyRoles, []),
    }
}

export const csmHudSceneLogic = kea<csmHudSceneLogicType>([
    path(['products', 'csm_hud', 'frontend', 'logics', 'csmHudSceneLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    selectors({
        csmEmail: [(s) => [s.user], (user): string | null => user?.email ?? null],
        // TODO restore before merge: gate behind FEATURE_FLAGS.SCENE_CSM_HUD + is_staff + @posthog.com
        canAccess: [() => [], (): boolean => true],
    }),
    loaders(({ values }) => ({
        fleet: [
            [] as FleetRow[],
            {
                loadFleet: async () => {
                    const csmEmail = values.csmEmail
                    if (!csmEmail || !values.canAccess) {
                        return []
                    }
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: FLEET_SQL,
                        values: {
                            csmPattern: `%"email":"${csmEmail}"%`,
                        },
                    }
                    const response = await api.query(query)
                    return (response.results ?? []).map(mapFleetRow)
                },
            },
        ],
    })),
    afterMount(({ actions, values }) => {
        if (values.canAccess) {
            actions.loadFleet()
        }
    }),
])
