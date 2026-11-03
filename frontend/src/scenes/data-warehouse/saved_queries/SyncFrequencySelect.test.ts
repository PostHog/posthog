import { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import {
    buildExplanation,
    buildOptions,
    defaultCadenceWithin,
    inheritedCadence,
    modeDisabledReason,
    pinNote,
    SyncFrequencyValue,
    speedUpViews,
    speedUpWarning,
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

    it.each([
        ['without pinning', {}, 'Too slow for downstream view daily_revenue', 'Every 1 day'],
        [
            'with pinning, a too-slow cadence names the views the pin delays',
            { canPin: true, pinDelays: { '24hour': [blocker('daily_revenue'), blocker('mrr')] } },
            undefined,
            'Pin this view to every 1 day. Downstream views daily_revenue, mrr refresh more often and will read older data from it.',
        ],
        [
            'with pinning, a too-slow cadence falls back to the view that caps it',
            { canPin: true },
            undefined,
            'Pin this view to every 1 day. Downstream view daily_revenue refreshes more often and will read older data from it.',
        ],
        [
            'with pinning, a pin that strands a downstream view stays off',
            { canPin: true, pinBlockedBy: { '24hour': blocker('maps') } },
            "Can't pin: downstream view maps reads fresh data only through this view",
            'Every 1 day',
        ],
    ])(
        'disables a blocked cadence and names what blocks it %s',
        (_case, pinOptions, consumerReason, consumerTooltip) => {
            const options = buildOptions(bounds(), pinOptions)

            const bySource = options.find((option) => option.value === '15min')
            const byConsumer = options.find((option) => option.value === '24hour')
            expect(bySource?.disabledReason).toBe('More often than upstream source stripe_invoices syncs')
            expect(byConsumer?.disabledReason).toBe(consumerReason)
            expect(byConsumer?.tooltip).toBe(consumerTooltip)
            expect(options.find((option) => option.value === '6hour')?.disabledReason).toBeUndefined()
        }
    )

    describe('pinNote', () => {
        it.each([
            [
                'a saved pin nothing reads faster than',
                false,
                [],
                'Pinned to refresh every 1 day, even when downstream views need fresher data.',
            ],
            [
                'a saved pin that delays one downstream view',
                false,
                ['daily_revenue'],
                'Pinned to refresh every 1 day. Downstream view daily_revenue refreshes more often, so it reads data up to 1 day old.',
            ],
            [
                'an unsaved pin that delays two downstream views',
                true,
                ['daily_revenue', 'mrr'],
                'Saving pins this view to refresh every 1 day. Downstream views daily_revenue, mrr refresh more often, so they read data up to 1 day old.',
            ],
        ])('describes %s', (_case, pending, names, expected) => {
            expect(pinNote('24hour', names.map(blocker), { pending })).toBe(expected)
        })
    })

    it('explains the range only where a per-view cadence is writable', () => {
        expect(buildExplanation(bounds())).toContain('Pick between 6 hours and 12 hours.')
        expect(buildExplanation(bounds({ frequency_mode: 'managed_viewset' }))).toBeNull()
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
                'No cadence works here: upstream source stripe_invoices only syncs every 6 hours, ' +
                    'but downstream view daily_revenue refreshes every 12 hours. ' +
                    'Slow down downstream view daily_revenue or speed up upstream source stripe_invoices.'
            )
        })

        it('asks for the source to speed up when only a floor blocks every cadence', () => {
            expect(unsatisfiableReason(nothingAllowed({ ceiling: null }))).toBe(
                'No cadence works here: upstream source stripe_invoices only syncs every 6 hours, ' +
                    'less often than anything this can refresh at. Speed up upstream source stripe_invoices first.'
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
                'More often than the upstream sources sync'
            )
            expect(options.find((option) => option.value === '24hour')?.disabledReason).toBe(
                'Too slow for a downstream view'
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

    describe('speedUpWarning', () => {
        const withSpeedsUp = (names: string[], withheld = false): SyncFrequencyBoundsApi =>
            bounds({
                options: [
                    {
                        cadence: '6hour',
                        allowed: true,
                        blocked_by: null,
                        blocker: null,
                        speeds_up: names.map(blocker),
                        speeds_up_withheld: withheld,
                    },
                ],
            } as Partial<SyncFrequencyBoundsApi>)

        it.each([
            ['nothing upstream is slower', [], false, null],
            [
                'one upstream view is slower',
                ['org_universe'],
                false,
                'Upstream view org_universe also refreshes every 6 hours to keep up with this view.',
            ],
            [
                'a slower upstream view is withheld',
                ['org_universe'],
                true,
                'Upstream views org_universe and others also refresh every 6 hours to keep up with this view.',
            ],
            [
                'every slower upstream view is withheld',
                [],
                true,
                'Some upstream views also refresh every 6 hours to keep up with this view.',
            ],
        ])('when %s', (_case, names, withheld, expected) => {
            expect(speedUpWarning(withSpeedsUp(names, withheld), '6hour')).toBe(expected)
        })

        it.each([
            [
                'names each slower upstream view it can pin',
                ['org_universe', 'accounts'],
                true,
                ['id-org_universe', 'id-accounts'],
            ],
            ['offers nothing to pin when every view is withheld', [], true, []],
        ])('%s', (_case, names, withheld, expectedIds) => {
            expect(speedUpViews(withSpeedsUp(names, withheld), '6hour').map((view) => view.id)).toEqual(expectedIds)
        })
    })

    describe('inheritedCadence', () => {
        const consumerBound = (name: string | null): SyncFrequencyBoundsApi =>
            bounds({
                options: [
                    {
                        cadence: '1hour',
                        allowed: true,
                        blocked_by: null,
                        blocker: null,
                        speeds_up: [],
                        speeds_up_withheld: false,
                    },
                    {
                        cadence: '6hour',
                        allowed: true,
                        blocked_by: null,
                        blocker: null,
                        speeds_up: [],
                        speeds_up_withheld: false,
                    },
                    {
                        cadence: '24hour',
                        allowed: false,
                        blocked_by: 'consumer',
                        blocker: null,
                        speeds_up: [],
                        speeds_up_withheld: false,
                    },
                ],
                ceiling: { label: '6 hours', blocker: name ? blocker(name) : null },
            } as Partial<SyncFrequencyBoundsApi>)

        it.each([
            ['the saved setting is allowed', consumerBound('maps'), '6hour', null],
            ['the view is paused', consumerBound('maps'), 'never', null],
            [
                'a consumer needs it fresher',
                consumerBound('maps'),
                '24hour',
                {
                    cadence: '6hour',
                    note: 'Refreshes every 6 hours to keep up with downstream view maps. Your 1 day setting applies again if downstream views refresh less often.',
                },
            ],
            [
                'the consumer is withheld',
                consumerBound(null),
                '24hour',
                {
                    cadence: '6hour',
                    note: 'Refreshes every 6 hours to keep up with a downstream view. Your 1 day setting applies again if downstream views refresh less often.',
                },
            ],
        ])('when %s', (_case, input, value, expected) => {
            expect(inheritedCadence(input, value as SyncFrequencyValue)).toEqual(expected)
        })
    })
})
