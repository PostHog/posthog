import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'
import { ExperimentHealthChip } from 'products/experiments/frontend/health/ExperimentHealthChip'
import { ExperimentHealthTab } from 'products/experiments/frontend/health/ExperimentHealthTab'

import { experimentLogic } from '../experimentLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'
import { Exposures } from './Exposures'
import { MultiVariantBiasWarning } from './MultiVariantBiasWarning'

const EXPERIMENT_ID = 7

// The exposure query returns a series for every configured variant, with zero counts when nobody was exposed.
const NO_EXPOSURES = {
    timeseries: [
        { variant: 'control', days: ['2026-01-01', '2026-01-02'], exposure_counts: [0, 0] },
        { variant: 'test', days: ['2026-01-01', '2026-01-02'], exposure_counts: [0, 0] },
    ],
    total_exposures: { control: 0, test: 0 },
}

const exposureFinding = (code: string, title: string, actions: string[]): Record<string, unknown> => ({
    code,
    subcode: null,
    reason: null,
    severity: 'warning',
    title,
    detail: title,
    evidence: {},
    actions,
    diagnostic_ref: null,
})

const UNEVEN_EXPOSURES = {
    timeseries: [
        { variant: 'control', days: ['2026-01-01', '2026-01-02'], exposure_counts: [300, 600] },
        { variant: 'test', days: ['2026-01-01', '2026-01-02'], exposure_counts: [200, 400] },
    ],
    total_exposures: { control: 600, test: 400 },
    date_range: { date_from: '2026-01-01', date_to: '2026-01-02' },
    sample_ratio_mismatch: { expected: { control: 500, test: 500 }, p_value: 0.0001 },
    bias_risk: { multiple_variant_percentage: 5 },
    health_findings: [
        exposureFinding('srm', 'Users are not split across variants as configured', []),
        exposureFinding('bias_risk_multiple_excluded', 'The uneven split may bias the results', [
            'adjust_distribution',
            'use_first_seen_variant',
        ]),
    ],
}

describe('health finding reporting', () => {
    let logic: ReturnType<typeof experimentLogic.build>
    let captureSpy: jest.SpyInstance

    const findingEvents = (): (string | undefined)[][] =>
        captureSpy.mock.calls
            .filter(([event]) => String(event).startsWith('experiment health finding'))
            .map(([event, properties]) => [
                event,
                properties.finding_code,
                properties.open_kind ?? properties.action_kind,
            ])

    // A running experiment whose flag is off, so the flag-state banner renders with its flag link.
    const renderWarnings = (exposures: Record<string, unknown>): void => {
        logic.actions.setExperiment({
            ...NEW_EXPERIMENT,
            id: EXPERIMENT_ID,
            status: ExperimentStatus.Running,
            start_date: dayjs().subtract(3, 'day').toISOString(),
            feature_flag: { id: 1, key: 'checkout-flag', active: false, filters: { groups: [] } },
        } as unknown as Experiment)
        logic.actions.loadExposuresSuccess(exposures)
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <ExperimentWarningBanner />
                    <Exposures />
                    <MultiVariantBiasWarning />
                </BindLogic>
            </Provider>
        )
    }

    // The same experiment for a person with the health findings flag: the server sends the flag-state finding.
    const renderHealth = (
        exposures: Record<string, unknown>,
        Surface: () => JSX.Element | null = ExperimentHealthTab
    ): void => {
        logic.actions.setExperiment({
            ...NEW_EXPERIMENT,
            id: EXPERIMENT_ID,
            status: ExperimentStatus.Running,
            start_date: dayjs().subtract(3, 'day').toISOString(),
            feature_flag: { id: 1, key: 'checkout-flag', active: false, filters: { groups: [] } },
        } as unknown as Experiment)
        logic.actions.loadExperimentHealthSuccess({
            findings: [
                {
                    code: 'flag_off_while_running',
                    subcode: 'running_but_flag_disabled',
                    reason: null,
                    severity: 'warning',
                    title: 'The experiment is paused',
                    detail: 'The linked feature flag is disabled while the experiment has not been ended.',
                    evidence: {},
                    actions: ['open_feature_flag'],
                    diagnostic_ref: 'A5',
                    check: 'flag_state',
                },
            ],
            checks: [
                {
                    key: 'no_metric',
                    name: 'Metrics not set up',
                    description: 'Checks that a launched experiment has at least one metric.',
                    status: 'passed',
                    reason: null,
                    values: {},
                    rule: null,
                    rows: [],
                },
            ],
        })
        logic.actions.loadExposuresSuccess(exposures)
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <BindLogic logic={experimentSceneLogic} props={{ experimentId: EXPERIMENT_ID }}>
                        <Surface />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    }

    // The detail repeats the title of the picked finding or check, and the list comes first in the page.
    const pickFromList = async (title: string): Promise<void> => {
        await userEvent.click(screen.getAllByText(title)[0])
    }

    beforeEach(() => {
        const emptyList = { count: 0, next: null, previous: null, results: [] }
        useMocks({
            get: {
                '/api/projects/:team/experiments': emptyList,
                '/api/projects/:team/experiment_holdouts': emptyList,
                '/api/projects/:team/experiment_saved_metrics': emptyList,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EXPERIMENT_HEALTH_FINDINGS], {
            [FEATURE_FLAGS.EXPERIMENT_HEALTH_FINDINGS]: true,
        })
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
        captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('reports each warning on screen as shown', () => {
        renderWarnings(UNEVEN_EXPOSURES)

        expect(findingEvents()).toEqual(
            expect.arrayContaining([
                ['experiment health finding shown', 'flag_off_while_running', undefined],
                ['experiment health finding shown', 'srm', undefined],
                ['experiment health finding shown', 'bias_risk_multiple_excluded', undefined],
            ])
        )
        expect(findingEvents()).toHaveLength(3)
    })

    it.each([
        {
            control: 'Adjust distribution',
            step: 'acted on',
            code: 'bias_risk_multiple_excluded',
            kind: 'adjust_distribution',
        },
        {
            control: 'Use first seen variant',
            step: 'acted on',
            code: 'bias_risk_multiple_excluded',
            kind: 'use_first_seen_variant',
        },
        { control: 'First seen', step: 'opened', code: 'bias_risk_multiple_excluded', kind: 'docs' },
        { control: 'checkout-flag', step: 'acted on', code: 'flag_off_while_running', kind: 'open_feature_flag' },
        { control: 'Exposures', step: 'opened', code: 'srm', kind: 'evidence' },
    ])('reports $code as $step with $kind when a person uses "$control"', async ({ control, step, code, kind }) => {
        renderWarnings(UNEVEN_EXPOSURES)
        captureSpy.mockClear()

        await userEvent.click(screen.getByText(control))

        expect(findingEvents()).toEqual([[`experiment health finding ${step}`, code, kind]])
    })

    it.each([
        { surface: 'header chip', Surface: ExperimentHealthChip },
        { surface: 'health tab', Surface: ExperimentHealthTab },
    ])('reports each issue as shown from the $surface, with the codes of the warnings it replaces', ({ Surface }) => {
        renderHealth(UNEVEN_EXPOSURES, Surface)

        const shown = captureSpy.mock.calls
            .filter(([event]) => event === 'experiment health finding shown')
            .map(([, properties]) => [properties.finding_code, properties.finding_subcode, properties.finding_severity])
        expect(shown).toEqual([
            ['flag_off_while_running', 'running_but_flag_disabled', 'warning'],
            ['srm', null, 'warning'],
            ['bias_risk_multiple_excluded', null, 'warning'],
        ])
    })

    it.each([
        {
            pick: 'The experiment is paused',
            control: 'Open feature flag',
            step: 'acted on',
            code: 'flag_off_while_running',
            kind: 'open_feature_flag',
        },
        {
            pick: 'The uneven split may bias the results',
            control: 'Use first seen variant',
            step: 'acted on',
            code: 'bias_risk_multiple_excluded',
            kind: 'use_first_seen_variant',
        },
    ])(
        'reports $code as $step with $kind when a person uses "$control" in the health tab',
        async ({ pick, control, step, code, kind }) => {
            renderHealth(UNEVEN_EXPOSURES)
            await pickFromList(pick)
            captureSpy.mockClear()

            await userEvent.click(screen.getByText(control))

            expect(findingEvents()).toEqual([[`experiment health finding ${step}`, code, kind]])
        }
    )

    it.each([
        {
            container: 'wide',
            isNarrow: false,
            expected: [
                ['experiment health finding opened', 'flag_off_while_running'],
                ['experiment health finding opened', 'srm'],
                ['experiment health check expanded', 'no_metric'],
                ['experiment health summary opened', undefined],
            ],
        },
        {
            container: 'narrow',
            isNarrow: true,
            expected: [
                ['experiment health finding opened', 'flag_off_while_running'],
                ['experiment health finding opened', 'srm'],
                ['experiment health finding opened', 'srm'],
                ['experiment health check expanded', 'no_metric'],
                ['experiment health summary opened', undefined],
                ['experiment health summary opened', undefined],
            ],
        },
    ])(
        'reports each finding, check or summary a person opens on the health tab in a $container container',
        async ({ isNarrow, expected }) => {
            // jsdom applies no container query, so the detail stays beside the list until `hidden` takes effect,
            // as it does below the breakpoint.
            const narrowStyles = document.head.appendChild(document.createElement('style'))
            narrowStyles.textContent = isNarrow ? '.hidden { display: none; }' : ''
            try {
                renderHealth(UNEVEN_EXPOSURES)
                expect(screen.getByText('Overview')).toBeInTheDocument()
                const pickEvents = (): (string | undefined)[][] =>
                    captureSpy.mock.calls
                        .filter(([event]) =>
                            [
                                'experiment health finding opened',
                                'experiment health check expanded',
                                'experiment health summary opened',
                            ].includes(String(event))
                        )
                        .map(([event, properties]) => [event, properties.finding_code ?? properties.check_key])
                expect(pickEvents()).toEqual([])

                // A narrow container shows the list or the detail, so the reader goes back to the list between picks.
                for (const title of [
                    'The experiment is paused',
                    'Users are not split across variants as configured',
                    'Users are not split across variants as configured',
                    'Metrics not set up',
                    'Health checks',
                    'Health checks',
                ]) {
                    await pickFromList(title)
                    if (isNarrow) {
                        await userEvent.click(screen.getByText('All checks'))
                    }
                }

                expect(pickEvents()).toEqual(expected)
            } finally {
                narrowStyles.remove()
            }
        }
    )

    it('reports zero exposures only from the open panel, as shown and then as opened', async () => {
        renderWarnings(NO_EXPOSURES)
        expect(findingEvents()).toEqual([['experiment health finding shown', 'flag_off_while_running', undefined]])
        captureSpy.mockClear()

        await userEvent.click(screen.getByText('Exposures'))
        expect(findingEvents()).toEqual([
            ['experiment health finding shown', 'zero_exposures', undefined],
            ['experiment health finding opened', 'zero_exposures', 'evidence'],
        ])
        captureSpy.mockClear()

        await userEvent.click(screen.getByText('Edit exposure criteria'))
        expect(findingEvents()).toEqual([
            ['experiment health finding acted on', 'zero_exposures', 'edit_exposure_criteria'],
        ])
    })
})
