// Compile-time checks: `pnpm --filter @posthog/sdk typecheck` fails when an expected error stops
// happening, or when a line meant to compile doesn't.
import {
    check,
    event,
    flag,
    insight,
    metric,
    model,
    prop,
    sql,
    typed,
    type DimensionsOf,
    type RowsOf,
} from '@posthog/sdk/define'

import type * as defs from '../fixtures/stack-all-kinds/index'

declare const posthog: {
    capture(
        event: string,
        properties?: Record<string, unknown> | null,
        options?: { send_instantly?: boolean }
    ): { uuid: string } | undefined
    getFeatureFlag(key: string): string | boolean | undefined
    identify(distinctId: string): void
    config: { api_host: string }
}

const analytics = typed<typeof defs>()(posthog)
// The one-call form, as the spec writes it, types capture the same way.
typed<typeof defs>(posthog).capture('checkout_completed', { account_id: 'a', order_id: 'o', total_usd: 1 })

analytics.capture('checkout_completed', { account_id: 'a', order_id: 'o', total_usd: 12 })
analytics.capture('checkout_completed', { account_id: 'a', order_id: 'o', total_usd: 12, plan: 'team' })
// @ts-expect-error account_id and total_usd are required
analytics.capture('checkout_completed', { order_id: 'o' })
// @ts-expect-error not a declared event
analytics.capture('checkout_done', {})
// @ts-expect-error plan takes only the declared members
analytics.capture('checkout_completed', { account_id: 'a', order_id: 'o', total_usd: 12, plan: 'enterprise' })
analytics.captureRaw('checkout_done', {})
// Undeclared properties may be sent alongside the declared ones, and the client's options and result come through.
const result: { uuid: string } | undefined = analytics.capture(
    'checkout_completed',
    { account_id: 'a', order_id: 'o', total_usd: 12, coupon: 'x' },
    { send_instantly: true }
)
// @ts-expect-error total_usd is a number
analytics.capture('checkout_completed', { account_id: 'a', order_id: 'o', total_usd: '12' })
// An event without required properties needs none.
analytics.capture('plan_upgraded', { account_id: 'a', from_plan: 'free' })
// The client's other members keep their own types.
analytics.identify('distinct-id')
const host: string = analytics.config.api_host
// @ts-expect-error identify takes a string
analytics.identify(42)

const variant: 'control' | 'test' | undefined = analytics.variant('new-checkout')
// @ts-expect-error not a declared flag
analytics.variant('old-checkout')

const checkout = event('checkout', {
    properties: { total: prop.number().required(), plan: prop.enum(['free', 'team']) },
})
// @ts-expect-error the event declares no property named nope
const undeclared = sql`select ${checkout.props.nope} from events`

const revenue = model('revenue', { columns: { total: 'number', plan: 'string', day: 'date' }, query: sql`select 1` })
const rows: RowsOf<typeof revenue> = [{ total: 1, plan: 'free', day: '2026-01-01' }]
// @ts-expect-error total is a number column
const wrongRows: RowsOf<typeof revenue> = [{ total: '1', plan: 'free', day: '2026-01-01' }]

const byPlan = metric('by_plan', { description: 'Total', from: revenue, column: 'total', dimensions: ['plan'] })
const dimension: DimensionsOf<typeof byPlan> = 'plan'
// @ts-expect-error the model declares no column named nope
metric('broken', { description: 'Broken', from: revenue, column: 'nope' })
// @ts-expect-error a check's column is one of its model's columns
check('broken_check', { subject: revenue, column_name: 'nope', check_type: 'not_null' })

// The long form of a trends insight type-checks as the API takes it.
const longForm = insight('long', {
    query: {
        kind: 'InsightVizNode',
        source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: 'signup' }], interval: 'day' },
    },
})

flag('plain')

export { byPlan, dimension, host, longForm, result, rows, undeclared, variant, wrongRows }

// A flag whose definition sets no variants may gain them in PostHog, so its value is not only a boolean.
const toggles = { beta: flag('beta', { payloads: { true: { theme: 'dark' } } }) }
const _toggle: boolean | string | undefined = typed<typeof toggles>()(posthog).variant('beta')
// @ts-expect-error a flag without variants in code may still return a variant
const _onlyBoolean: boolean | undefined = typed<typeof toggles>()(posthog).variant('beta')
// @ts-expect-error variants are set with the variants option, so typed().variant() knows them
flag('moved', { filters: { multivariate: { variants: [{ key: 'a', rollout_percentage: 100 }] } } })
// @ts-expect-error payloads are keyed by the flag's variants
flag('keyed', { variants: ['a', 'b'], payloads: { c: 1 } })
