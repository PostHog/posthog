import { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import {
    buildExplanation,
    buildOptions,
    defaultCadenceWithin,
    modeDisabledReason,
    unsatisfiableReason,
} from './SyncFrequencySelect'

describe('SyncFrequencySelect', () => {
    const blocker = (name: string): { id: string; name: string } => ({ id: `id-${name}`, name })

    const bounds = (overrides: Partial<SyncFrequencyBoundsApi> = {}): SyncFrequencyBoundsApi =>
        ({
            frequency_mode: 'tiered',
            options: [
                { cadence: '15min', allowed: false, blocked_by: 'source', blocker: blocker('stripe_invoices') },
                { cadence: '6hour', allowed: true, blocked_by: null, blocker: null },
                { cadence: '24hour', allowed: false, blocked_by: 'consumer', blocker: blocker('daily_revenue') },
            ],
            floor: { label: '6 hours', blocker: blocker('stripe_invoices') },
            ceiling: { label: '12 hours', blocker: blocker('daily_revenue') },
            best_effort_sources: [],
            best_effort_sources_withheld: false,
            ...overrides,
        }) as SyncFrequencyBoundsApi

    it('offers every cadence when the backend sends no bounds', () => {
        const options = buildOptions(null)

        expect(options).toHaveLength(8)
        expect(options.every((option) => !option.disabledReason)).toBe(true)
    })

    it('disables a blocked cadence and names what blocks it', () => {
        const options = buildOptions(bounds())

        const bySource = options.find((option) => option.value === '15min')
        const byConsumer = options.find((option) => option.value === '24hour')
        expect(bySource?.disabledReason).toBe('More often than stripe_invoices syncs')
        expect(byConsumer?.disabledReason).toBe('Too slow for daily_revenue')
        expect(options.find((option) => option.value === '6hour')?.disabledReason).toBeUndefined()
    })

    it('explains the range only where a per-view cadence is writable', () => {
        expect(buildExplanation(bounds())).toContain('Pick between 6 hours and 12 hours.')
        expect(buildExplanation(bounds({ frequency_mode: 'dag_schedule' }))).toBeNull()
        expect(buildExplanation(bounds({ floor: null, ceiling: null }))).toBeNull()
    })

    describe('defaultCadenceWithin', () => {
        const withAllowed = (...allowed: string[]): SyncFrequencyBoundsApi =>
            bounds({
                options: ['15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'].map((cadence) => ({
                    cadence,
                    allowed: allowed.includes(cadence),
                    blocked_by: null,
                    blocker: null,
                })),
            } as Partial<SyncFrequencyBoundsApi>)

        it('keeps the preferred cadence when the lineage allows it', () => {
            expect(defaultCadenceWithin(withAllowed('6hour', '24hour'), '24hour')).toBe('24hour')
        })

        it('drops to the coarsest allowed cadence when a consumer rules the default out', () => {
            // A sub-daily consumer is exactly the case that made Materialize a dead end.
            expect(defaultCadenceWithin(withAllowed('15min', '30min', '1hour'), '24hour')).toBe('1hour')
        })

        it('goes finer only when nothing coarser than the default is allowed', () => {
            expect(defaultCadenceWithin(withAllowed('7day', '30day'), '24hour')).toBe('30day')
        })

        it('leaves the preferred cadence alone when there are no bounds to honor', () => {
            expect(defaultCadenceWithin(null, '24hour')).toBe('24hour')
        })
    })

    describe('unsatisfiableReason', () => {
        const nothingAllowed = (overrides: Partial<SyncFrequencyBoundsApi> = {}): SyncFrequencyBoundsApi =>
            bounds({
                options: ['15min', '6hour', '24hour'].map((cadence) => ({
                    cadence,
                    allowed: false,
                    blocked_by: null,
                    blocker: null,
                })),
                ...overrides,
            } as Partial<SyncFrequencyBoundsApi>)

        it('names both ends and what to change when the bounds cross', () => {
            // Every cadence blocked means Materialize would 400 whatever the picker had selected.
            expect(unsatisfiableReason(nothingAllowed())).toBe(
                'No cadence works here: stripe_invoices only syncs every 6 hours, ' +
                    'but daily_revenue refreshes every 12 hours. ' +
                    'Slow down daily_revenue or speed up stripe_invoices.'
            )
        })

        it('asks for the source to speed up when only a floor blocks every cadence', () => {
            expect(unsatisfiableReason(nothingAllowed({ ceiling: null }))).toBe(
                'No cadence works here: stripe_invoices only syncs every 6 hours, ' +
                    'less often than anything this can refresh at. Speed up stripe_invoices first.'
            )
        })

        it('stays silent while any cadence is still allowed', () => {
            expect(unsatisfiableReason(bounds())).toBeNull()
            expect(unsatisfiableReason(null)).toBeNull()
        })
    })

    it('warns that a source with no schedule makes the floor a guess', () => {
        const explanation = buildExplanation(bounds({ best_effort_sources: [blocker('hubspot_contacts')] }))

        expect(explanation).toContain('hubspot_contacts has no sync schedule')
    })

    describe('a blocker outside the caller access grants', () => {
        // The backend nulls the whole blocker rather than blanking its name, so every surface that
        // would have named it has to still say which direction blocks the cadence.
        it('keeps the direction on a blocked segment', () => {
            const options = buildOptions(
                bounds({
                    options: [
                        { cadence: '15min', allowed: false, blocked_by: 'source', blocker: null },
                        { cadence: '24hour', allowed: false, blocked_by: 'consumer', blocker: null },
                    ],
                } as Partial<SyncFrequencyBoundsApi>)
            )

            expect(options.find((option) => option.value === '15min')?.disabledReason).toBe(
                'More often than the sources this view reads'
            )
            expect(options.find((option) => option.value === '24hour')?.disabledReason).toBe(
                'Too slow for something built on this view'
            )
        })

        it('still states the range under the bar', () => {
            const explanation = buildExplanation(
                bounds({
                    floor: { label: '6 hours', blocker: null },
                    ceiling: { label: '12 hours', blocker: null },
                })
            )

            expect(explanation).toBe(
                'Pick between 6 hours and 12 hours. An upstream source syncs every 6 hours, ' +
                    'and a downstream view refreshes every 12 hours.'
            )
        })

        it('still explains why no cadence works', () => {
            const nothingAllowed = bounds({
                options: [{ cadence: '6hour', allowed: false, blocked_by: 'source', blocker: null }],
                floor: { label: '6 hours', blocker: null },
                ceiling: null,
            } as Partial<SyncFrequencyBoundsApi>)

            expect(unsatisfiableReason(nothingAllowed)).toBe(
                'No cadence works here: an upstream source only syncs every 6 hours, ' +
                    'less often than anything this can refresh at. Speed up an upstream source first.'
            )
        })

        it('keeps the best-effort caveat when every such source is withheld', () => {
            const explanation = buildExplanation(
                bounds({ best_effort_sources: [], best_effort_sources_withheld: true })
            )

            expect(explanation).toContain('Some sources upstream have no sync schedule')
        })

        it('says there are more when only some are withheld', () => {
            const explanation = buildExplanation(
                bounds({ best_effort_sources: [blocker('hubspot_contacts')], best_effort_sources_withheld: true })
            )

            expect(explanation).toContain('hubspot_contacts and other sources upstream have no sync schedule')
        })
    })
    describe('modeDisabledReason', () => {
        it.each([
            ['dag_schedule', 'This view refreshes on a shared schedule. Its frequency is not set per view.'],
            ['managed_viewset', 'PostHog manages this view, including how often it refreshes.'],
            ['no_node', 'This view is not set up for scheduled refreshes yet. Save it again, then pick a cadence.'],
        ])('locks %s, where the backend refuses the write', (mode, reason) => {
            const locked = bounds({ frequency_mode: mode as SyncFrequencyBoundsApi['frequency_mode'] })

            expect(modeDisabledReason(locked)).toBe(reason)
        })

        it('leaves a tiered view editable', () => {
            expect(modeDisabledReason(bounds())).toBeNull()
        })
    })
})
