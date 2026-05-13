import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { detectMissingSources, MissingSourceKind } from '../utils/missingSources'
import type { ProjectionRow } from '../utils/projection'

// Strict allowlist: identifiers we're willing to interpolate into `IN (...)` literals.
// Mirrors the Python sanitizer in cs-toolkit posthog._sanitize_token — anything
// outside [A-Za-z0-9_-] is dropped, which covers both org UUIDs and Stripe
// customer ids (`cus_<alphanumeric>`). HogQL placeholders don't currently
// expand into IN-tuples cleanly, so we keep the same approach.
function sanitizeIdList(values: string[]): string {
    const safe = values.map((v) => v.replace(/[^A-Za-z0-9_-]/g, '')).filter((v) => v.length > 0)
    if (safe.length === 0) {
        return "''"
    }
    return safe.map((v) => `'${v}'`).join(', ')
}

interface BillingRow {
    organizationId: string
    periodStarts: string | null
    periodEnds: string | null
    priorMonthMrr: number
    currentMonthSpend: number
}

interface ContractsRow {
    organizationId: string
    contractStart: string | null
    contractEnd: string | null
    termMonths: number | null
    arrDiscounted: number | null
    opportunityName: string | null
}

interface OwnersRow {
    organizationId: string
    csm: string | null
    ae: string | null
    managedBy: string | null
}

interface MrrHistoryRow {
    organizationId: string
    m2Actual: number
    m3Actual: number
}

interface ChargesRow {
    customerId: string
    recentChargeCount: number
    mtdStripe: number | null
    lastChargeUsd: number | null
    lastChargeDate: string | null
    lastChargeStatus: string | null
}

interface InvoiceRow {
    customerId: string
    invoiceDate: string
    subtotal: number
    amountPaid: number
}

async function runHogQL<T>(name: string, query: string, mapRow: (row: unknown[]) => T): Promise<T[]> {
    const node: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query,
        tags: { productKey: 'internal', scene: 'CSMHud', name: `csm_hud_${name}` },
    }
    const response = await api.query(node)
    return (response.results ?? []).map(mapRow)
}

/**
 * Run a single slice query, swallowing only "Unknown table" errors. Detected
 * missing sources are pushed into the shared accumulator so the orchestrator
 * can report all of them at once instead of stopping at the first failure.
 */
async function tolerantSlice<T>(missing: Set<MissingSourceKind>, fn: () => Promise<T[]>): Promise<T[]> {
    try {
        return await fn()
    } catch (err) {
        const ms = detectMissingSources(err)
        if (ms.length === 0) {
            throw err
        }
        ms.forEach((s) => missing.add(s))
        return []
    }
}

const toFloat = (v: unknown): number => {
    if (v == null || v === '') {
        return 0
    }
    const n = typeof v === 'number' ? v : parseFloat(String(v))
    return Number.isFinite(n) ? n : 0
}
const toFloatOrNull = (v: unknown): number | null => {
    if (v == null || v === '') {
        return null
    }
    const n = typeof v === 'number' ? v : parseFloat(String(v))
    return Number.isFinite(n) ? n : null
}
const toStringOrNull = (v: unknown): string | null => {
    if (v == null) {
        return null
    }
    const s = String(v)
    return s.length === 0 ? null : s
}

function billingSql(orgIds: string[]): string {
    const orgIn = sanitizeIdList(orgIds)
    return `
SELECT
  cbs.organization_id AS organization_id,
  toString(cbs.billing_period_starts) AS period_starts,
  toString(cbs.billing_period_ends) AS period_ends,
  round(coalesce(cbs.last_invoice_mrr, 0), 2) AS prior_month_mrr,
  round(coalesce(inv.subtotal / 100, 0), 2) AS current_month_spend
FROM customer_billing_summary cbs
LEFT JOIN (
  SELECT
    customer_id,
    argMax(JSONExtractFloat(data, 'subtotal'), updated_at) AS subtotal
  FROM prod_postgres_billing_upcominginvoice
  WHERE customer_id IN (
    SELECT customer_id FROM customer_billing_summary
    WHERE organization_id IN (${orgIn})
  )
  GROUP BY customer_id
) inv ON inv.customer_id = cbs.customer_id
WHERE cbs.organization_id IN (${orgIn})
LIMIT 500
`.trim()
}

function contractsSql(orgIds: string[]): string {
    const orgIn = sanitizeIdList(orgIds)
    return `
SELECT
  o.post_hog_org_id_c AS organization_id,
  toString(toDate(argMax(o.contract_start_date_c, o.contract_end_date_c))) AS contract_start,
  toString(toDate(max(o.contract_end_date_c))) AS contract_end,
  argMax(o.term_months_c, o.contract_end_date_c) AS term_months,
  argMax(o.arr_discounted_c, o.contract_end_date_c) AS arr_discounted,
  argMax(o.name, o.contract_end_date_c) AS opportunity_name
FROM salesforce.opportunity o
WHERE o.is_won = true
  AND o.is_deleted = false
  AND o.contract_end_date_c != ''
  AND o.contract_end_date_c IS NOT NULL
  AND o.post_hog_org_id_c IN (${orgIn})
GROUP BY o.post_hog_org_id_c
LIMIT 500
`.trim()
}

function ownersSql(orgIds: string[]): string {
    const orgIn = sanitizeIdList(orgIds)
    return `
SELECT
  bcwo.organization_id AS organization_id,
  bcwo.current_owner_name AS csm,
  bcwo.ae_name AS ae,
  bcwo.managed_by AS managed_by
FROM billing_customers_with_owner bcwo
WHERE bcwo.organization_id IN (${orgIn})
LIMIT 500
`.trim()
}

function mrrHistorySql(orgIds: string[]): string {
    const orgIn = sanitizeIdList(orgIds)
    return `
SELECT
  m.organization_id AS organization_id,
  round(sumIf(m.mrr_value, toStartOfMonth(toDate(m.month)) = toStartOfMonth(today() - interval 2 month)), 2) AS m2_actual,
  round(sumIf(m.mrr_value, toStartOfMonth(toDate(m.month)) = toStartOfMonth(today() - interval 3 month)), 2) AS m3_actual
FROM iwa_org_month_product_mrr_usage m
WHERE m.metric = 'total_mrr'
  AND m.selected_type = 'completed'
  AND toDate(m.month) >= toStartOfMonth(today() - interval 3 month)
  AND toDate(m.month) <= toStartOfMonth(today() - interval 2 month)
  AND m.organization_id IN (${orgIn})
GROUP BY m.organization_id
LIMIT 500
`.trim()
}

function chargesSql(stripeIds: string[]): string {
    const stripeIn = sanitizeIdList(stripeIds)
    return `
SELECT
  ch.customer_id AS customer_id,
  countIf(toDate(ch.created) >= today() - interval 90 day) AS recent_charge_count,
  round(sumIf(ch.amount / 100, toStartOfMonth(toDate(ch.created)) = toStartOfMonth(today())), 2) AS mtd_stripe,
  round(argMax(ch.amount, ch.created) / 100.0, 2) AS last_charge_usd,
  toString(argMax(toDate(ch.created), ch.created)) AS last_charge_date,
  argMax(ch.status, ch.created) AS last_charge_status
FROM postgres.revenue.charge ch
WHERE ch.paid = true
  AND toDate(ch.created) >= today() - interval 3 month
  AND ch.customer_id IN (${stripeIn})
GROUP BY ch.customer_id
LIMIT 500
`.trim()
}

function invoicesSql(stripeIds: string[]): string {
    const stripeIn = sanitizeIdList(stripeIds)
    return `
SELECT
  customer_id,
  toString(toDate(created)) AS invoice_date,
  round(coalesce(subtotal, 0) / 100.0, 2) AS subtotal,
  round(coalesce(amount_paid, 0) / 100.0, 2) AS amount_paid
FROM revenuepostgres_invoice
WHERE customer_id IN (${stripeIn})
  AND status = 'paid'
  AND billing_reason = 'subscription_cycle'
  AND coalesce(is_deleted, false) = false
  AND toDate(created) >= today() - interval 6 month
ORDER BY customer_id, created DESC
LIMIT 500
`.trim()
}

function computeDerived(
    m1: number,
    m2: number,
    m3: number,
    mtdActual: number,
    periodStarts: string | null,
    periodEnds: string | null,
    recentCharges: number
): {
    weightedBaseline: number
    forecastedMrr: number
    historyMonths: number
    isPrepaidCreditAcct: boolean
} {
    const historyMonths = (m1 > 0 ? 1 : 0) + (m2 > 0 ? 1 : 0) + (m3 > 0 ? 1 : 0)
    const w1 = m1 > 0 ? 0.5 : 0
    const w2 = m2 > 0 ? 0.3 : 0
    const w3 = m3 > 0 ? 0.2 : 0
    const weightsSum = w1 + w2 + w3
    const weightedBaseline = weightsSum > 0 ? (m1 * 0.5 + m2 * 0.3 + m3 * 0.2) / weightsSum : 0

    let daysRemaining = 0
    let totalDays = 1
    if (periodStarts && periodEnds) {
        const ps = new Date(periodStarts.slice(0, 10))
        const pe = new Date(periodEnds.slice(0, 10))
        if (!Number.isNaN(ps.getTime()) && !Number.isNaN(pe.getTime())) {
            const today = new Date()
            const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
            daysRemaining = Math.max(0, Math.floor((pe.getTime() - todayUtc) / 86_400_000))
            totalDays = Math.max(1, Math.floor((pe.getTime() - ps.getTime()) / 86_400_000))
        }
    }

    const forecastedMrr = mtdActual + weightedBaseline * (daysRemaining / totalDays)
    return {
        weightedBaseline: Math.round(weightedBaseline * 100) / 100,
        forecastedMrr: Math.round(forecastedMrr * 100) / 100,
        historyMonths,
        isPrepaidCreditAcct: m1 > 0 && recentCharges === 0,
    }
}

export interface ProjectionInputs {
    /** organizationId for every account in the CSM's fleet. */
    orgIds: string[]
    /** name keyed by organizationId — passed through to ProjectionRow.name. */
    nameByOrg: Record<string, string>
    /** stripe customer id keyed by organizationId, where one exists. */
    stripeByOrg: Record<string, string>
}

export interface ProjectionResult {
    data: Record<string, ProjectionRow>
    missingSources: MissingSourceKind[]
}

export async function loadProjection({ orgIds, nameByOrg, stripeByOrg }: ProjectionInputs): Promise<ProjectionResult> {
    if (orgIds.length === 0) {
        return { data: {}, missingSources: [] }
    }
    const stripeIds = Object.values(stripeByOrg).filter(Boolean)
    const missing = new Set<MissingSourceKind>()

    // Sequential — PostHog's HogQL concurrency guard rejects parallel submits
    // on the same project. Each slice is sub-second; total bound is ~6s.
    // tolerantSlice catches "Unknown table" per slice so a single missing
    // source doesn't black out the others.
    const billing = await tolerantSlice(missing, () =>
        runHogQL<BillingRow>('projection_billing', billingSql(orgIds), (row) => ({
            organizationId: String(row[0] ?? ''),
            periodStarts: toStringOrNull(row[1]),
            periodEnds: toStringOrNull(row[2]),
            priorMonthMrr: toFloat(row[3]),
            currentMonthSpend: toFloat(row[4]),
        }))
    )
    const contracts = await tolerantSlice(missing, () =>
        runHogQL<ContractsRow>('projection_contracts', contractsSql(orgIds), (row) => ({
            organizationId: String(row[0] ?? ''),
            contractStart: toStringOrNull(row[1]),
            contractEnd: toStringOrNull(row[2]),
            termMonths: toFloatOrNull(row[3]),
            arrDiscounted: toFloatOrNull(row[4]),
            opportunityName: toStringOrNull(row[5]),
        }))
    )
    const owners = await tolerantSlice(missing, () =>
        runHogQL<OwnersRow>('projection_owners', ownersSql(orgIds), (row) => ({
            organizationId: String(row[0] ?? ''),
            csm: toStringOrNull(row[1]),
            ae: toStringOrNull(row[2]),
            managedBy: toStringOrNull(row[3]),
        }))
    )
    const mrr = await tolerantSlice(missing, () =>
        runHogQL<MrrHistoryRow>('projection_mrr_history', mrrHistorySql(orgIds), (row) => ({
            organizationId: String(row[0] ?? ''),
            m2Actual: toFloat(row[1]),
            m3Actual: toFloat(row[2]),
        }))
    )
    const charges =
        stripeIds.length > 0
            ? await tolerantSlice(missing, () =>
                  runHogQL<ChargesRow>('projection_charges', chargesSql(stripeIds), (row) => ({
                      customerId: String(row[0] ?? ''),
                      recentChargeCount: toFloat(row[1]),
                      mtdStripe: toFloatOrNull(row[2]),
                      lastChargeUsd: toFloatOrNull(row[3]),
                      lastChargeDate: toStringOrNull(row[4]),
                      lastChargeStatus: toStringOrNull(row[5]),
                  }))
              )
            : []
    const invoices =
        stripeIds.length > 0
            ? await tolerantSlice(missing, () =>
                  runHogQL<InvoiceRow>('projection_invoices', invoicesSql(stripeIds), (row) => ({
                      customerId: String(row[0] ?? ''),
                      invoiceDate: String(row[1] ?? ''),
                      subtotal: toFloat(row[2]),
                      amountPaid: toFloat(row[3]),
                  }))
              )
            : []

    const billingByOrg = new Map(billing.map((r) => [r.organizationId, r]))
    const contractsByOrg = new Map(contracts.map((r) => [r.organizationId, r]))
    const ownersByOrg = new Map(owners.map((r) => [r.organizationId, r]))
    const mrrByOrg = new Map(mrr.map((r) => [r.organizationId, r]))
    const chargesByCust = new Map(charges.map((r) => [r.customerId, r]))

    // Group invoices by stripe customer, keep top-3 (SQL sorts DESC).
    const invoicesByCust = new Map<string, InvoiceRow[]>()
    for (const r of invoices) {
        const bucket = invoicesByCust.get(r.customerId) ?? []
        if (bucket.length < 3) {
            bucket.push(r)
            invoicesByCust.set(r.customerId, bucket)
        }
    }

    const result: Record<string, ProjectionRow> = {}
    for (const oid of orgIds) {
        const b = billingByOrg.get(oid)
        const c = contractsByOrg.get(oid)
        const ow = ownersByOrg.get(oid)
        const m = mrrByOrg.get(oid)
        const sid = stripeByOrg[oid]
        const ch = sid ? chargesByCust.get(sid) : undefined
        const invs = sid ? (invoicesByCust.get(sid) ?? []) : []

        // Invoice subtotals are authoritative — cbs.last_invoice_mrr returns 0
        // for credit-funded customers (latent bug in the warehouse summary).
        const inv1 = invs[0]
        const inv2 = invs[1]
        const inv3 = invs[2]
        const priorMonthMrr = inv1 ? inv1.subtotal : (b?.priorMonthMrr ?? 0)
        const m2Actual = inv2 ? inv2.subtotal : (m?.m2Actual ?? 0)
        const m3Actual = inv3 ? inv3.subtotal : (m?.m3Actual ?? 0)
        const currentMonthSpend = b?.currentMonthSpend ?? 0
        const recentCharges = ch?.recentChargeCount ?? 0

        const derived = computeDerived(
            priorMonthMrr,
            m2Actual,
            m3Actual,
            currentMonthSpend,
            b?.periodStarts ?? null,
            b?.periodEnds ?? null,
            recentCharges
        )

        result[oid] = {
            externalId: oid,
            name: nameByOrg[oid] ?? '',
            currentMonthSpend,
            priorMonthMrr,
            m2Actual,
            m3Actual,
            m1Paid: inv1 ? inv1.amountPaid : null,
            m2Paid: inv2 ? inv2.amountPaid : null,
            m3Paid: inv3 ? inv3.amountPaid : null,
            weightedBaseline: derived.weightedBaseline,
            forecastedMrr: derived.forecastedMrr,
            historyMonths: derived.historyMonths,
            isPrepaidCreditAcct: derived.isPrepaidCreditAcct,
            mtdStripe: ch?.mtdStripe ?? null,
            lastChargeUsd: ch?.lastChargeUsd ?? null,
            lastChargeDate: ch?.lastChargeDate ?? null,
            lastChargeStatus: ch?.lastChargeStatus ?? null,
            periodStarts: b?.periodStarts ?? null,
            periodEnds: b?.periodEnds ?? null,
            contractStart: c?.contractStart ?? null,
            contractEnd: c?.contractEnd ?? null,
            termMonths: c?.termMonths ?? null,
            arrDiscounted: c?.arrDiscounted ?? null,
            opportunityName: c?.opportunityName ?? null,
            csm: ow?.csm ?? null,
            ae: ow?.ae ?? null,
            managedBy: ow?.managedBy ?? null,
        }
    }
    return { data: result, missingSources: Array.from(missing) }
}
