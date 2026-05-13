import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { detectMissingSources, MissingSourceKind } from '../utils/missingSources'

export interface NrrSnapshot {
    accountsInCalc: number
    accountsExcludedInactive: number
    accountsExcludedRefundOnly: number
    accountsTotal: number
    sumRecent6mo: number
    sumPrior6mo: number
    nrrPct: number | null
}

export interface NrrResult {
    snapshot: NrrSnapshot | null
    missingSources: MissingSourceKind[]
}

function nrrSql(csmEmail: string | null): { query: string; values?: Record<string, unknown> } {
    // csm_orgs CTE scopes to the same fleet the scene-level csmFilter selects;
    // empty filter means "every account with any CSM assigned" — matches the
    // Fleet tab behavior.
    const csmFilterClause = csmEmail == null ? '' : `\n    AND key_roles LIKE {csmPattern}`
    const query = `
WITH csm_orgs AS (
  SELECT external_id AS organization_id
  FROM vitally_accounts
  WHERE key_roles LIKE '%"label":"CSM"%'${csmFilterClause}
),
monthly AS (
  SELECT
    organization_id,
    sumIf(mrr_value, toStartOfMonth(toDate(month)) >= toStartOfMonth(today() - interval 6 month) AND toStartOfMonth(toDate(month)) <= toStartOfMonth(today() - interval 1 month)) AS recent_6mo,
    sumIf(mrr_value, toStartOfMonth(toDate(month)) >= toStartOfMonth(today() - interval 12 month) AND toStartOfMonth(toDate(month)) <= toStartOfMonth(today() - interval 7 month)) AS prior_6mo
  FROM iwa_org_month_product_mrr_usage
  WHERE metric = 'total_mrr'
    AND selected_type = 'completed'
    AND organization_id IN (SELECT organization_id FROM csm_orgs)
  GROUP BY organization_id
),
joined AS (
  SELECT
    c.organization_id AS organization_id,
    coalesce(m.recent_6mo, 0) AS recent_6mo,
    coalesce(m.prior_6mo, 0) AS prior_6mo
  FROM csm_orgs c
  LEFT JOIN monthly m ON m.organization_id = c.organization_id
)
SELECT
  countIf(prior_6mo > 0) AS accounts_in_calc,
  countIf(prior_6mo <= 0 AND recent_6mo = 0) AS accounts_excluded_inactive,
  countIf(prior_6mo <= 0 AND recent_6mo != 0) AS accounts_excluded_refund_only,
  count() AS accounts_total,
  round(sumIf(recent_6mo, prior_6mo > 0), 0) AS sum_recent_6mo,
  round(sumIf(prior_6mo, prior_6mo > 0), 0) AS sum_prior_6mo,
  round((sumIf(recent_6mo, prior_6mo > 0) / nullIf(sumIf(prior_6mo, prior_6mo > 0), 0)) * 100, 1) AS nrr_pct
FROM joined
LIMIT 1
`.trim()
    if (csmEmail == null) {
        return { query }
    }
    return { query, values: { csmPattern: `%"email":"${csmEmail}"%` } }
}

const toFloat = (v: unknown): number => {
    if (v == null || v === '') {
        return 0
    }
    const n = typeof v === 'number' ? v : parseFloat(String(v))
    return Number.isFinite(n) ? n : 0
}
const toInt = (v: unknown): number => {
    if (v == null || v === '') {
        return 0
    }
    const n = typeof v === 'number' ? v : parseInt(String(v), 10)
    return Number.isFinite(n) ? n : 0
}

export async function loadNrr(csmEmail: string | null): Promise<NrrResult> {
    const { query, values } = nrrSql(csmEmail)
    const node: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query,
        tags: { productKey: 'internal', scene: 'CSMHud', name: 'csm_hud_nrr' },
        ...(values ? { values } : {}),
    }
    try {
        const response = await api.query(node)
        const row = (response.results ?? [])[0]
        if (!row) {
            return { snapshot: null, missingSources: [] }
        }
        return {
            snapshot: {
                accountsInCalc: toInt(row[0]),
                accountsExcludedInactive: toInt(row[1]),
                accountsExcludedRefundOnly: toInt(row[2]),
                accountsTotal: toInt(row[3]),
                sumRecent6mo: toFloat(row[4]),
                sumPrior6mo: toFloat(row[5]),
                nrrPct: row[6] == null ? null : toFloat(row[6]),
            },
            missingSources: [],
        }
    } catch (err) {
        const missing = detectMissingSources(err)
        if (missing.length === 0) {
            throw err
        }
        return { snapshot: null, missingSources: missing }
    }
}
