import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'
import { ExperimentHealthPanel } from 'products/experiments/frontend/health/ExperimentHealthPanel'

import { experimentLogic } from '../experimentLogic'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'
import { Exposures } from './Exposures'
import { MultiVariantBiasWarning } from './MultiVariantBiasWarning'

const EXPERIMENT_ID = 7

const NO_EXPOSURES = { timeseries: [], total_exposures: {} }

const UNEVEN_EXPOSURES = {
    timeseries: [
        { variant: 'control', days: ['2026-01-01', '2026-01-02'], exposure_counts: [300, 600] },
        { variant: 'test', days: ['2026-01-01', '2026-01-02'], exposure_counts: [200, 400] },
    ],
    total_exposures: { control: 600, test: 400 },
    sample_ratio_mismatch: { expected: { control: 500, test: 500 }, p_value: 0.0001 },
    bias_risk: { multiple_variant_percentage: 5 },
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
    const renderHealthPanel = (exposures: Record<string, unknown>): void => {
        logic.actions.setExperiment({
            ...NEW_EXPERIMENT,
            id: EXPERIMENT_ID,
            status: ExperimentStatus.Running,
            start_date: dayjs().subtract(3, 'day').toISOString(),
            feature_flag: { id: 1, key: 'checkout-flag', active: false, filters: { groups: [] } },
            health: {
                findings: [
                    {
                        code: 'flag_off_while_running',
                        subcode: 'running_but_flag_disabled',
                        severity: 'warning',
                        title: 'The experiment is paused',
                        detail: 'The linked feature flag is disabled while the experiment has not been ended.',
                        evidence: {},
                        actions: ['open_feature_flag'],
                        diagnostic_ref: 'A5',
                    },
                ],
            },
        } as unknown as Experiment)
        logic.actions.loadExposuresSuccess(exposures)
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <ExperimentHealthPanel />
                </BindLogic>
            </Provider>
        )
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

    it('reports each finding of the health panel as shown, with the codes of the warnings it replaces', () => {
        renderHealthPanel(UNEVEN_EXPOSURES)

        const shown = captureSpy.mock.calls
            .filter(([event]) => event === 'experiment health finding shown')
            .map(([, properties]) => [properties.finding_code, properties.finding_variant])
        expect(shown).toEqual([
            ['flag_off_while_running', 'running_but_flag_disabled'],
            ['srm', null],
            ['bias_risk_multiple_excluded', null],
        ])
    })

    it.each([
        { control: 'Open feature flag', step: 'acted on', code: 'flag_off_while_running', kind: 'open_feature_flag' },
        {
            control: 'Use first seen variant',
            step: 'acted on',
            code: 'bias_risk_multiple_excluded',
            kind: 'use_first_seen_variant',
        },
    ])(
        'reports $code as $step with $kind when a person uses "$control" in the health panel',
        async ({ control, step, code, kind }) => {
            renderHealthPanel(UNEVEN_EXPOSURES)
            captureSpy.mockClear()

            await userEvent.click(screen.getByText(control))

            expect(findingEvents()).toEqual([[`experiment health finding ${step}`, code, kind]])
        }
    )

    it('reports a finding of the health panel as opened when a person opens its detail', async () => {
        renderHealthPanel(NO_EXPOSURES)
        captureSpy.mockClear()

        const [flagStateWhy] = screen.getAllByText('Why?')
        await userEvent.click(flagStateWhy)
        expect(screen.getByText(/The linked feature flag is disabled/)).toBeInTheDocument()
        await userEvent.click(flagStateWhy)

        expect(findingEvents()).toEqual([['experiment health finding opened', 'flag_off_while_running', 'why']])
    })

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
