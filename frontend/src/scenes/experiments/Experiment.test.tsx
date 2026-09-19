import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ExperimentStatus, type Experiment as ExperimentType } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { experimentsLogic } from '../../../../products/experiments/frontend/scenes/experimentsLogic'
import { Experiment } from './Experiment'
import { FORM_MODES } from './experimentLogic'
import { experimentSceneLogic } from './experimentSceneLogic'

jest.mock('lib/customerJourneys/startCustomerJourney')

jest.mock('./ExperimentWizard/ExperimentWizard', () => ({
    ExperimentWizard: () => <div data-attr="experiment-wizard" />,
}))

jest.mock('lib/hooks/useFileSystemLogView', () => ({
    useFileSystemLogView: () => {},
}))

jest.mock('scenes/feature-flags/JSONEditorInput', () => ({
    JSONEditorInput: ({ onChange, value, placeholder, readOnly }: any) => (
        <input
            data-attr="json-editor-mock"
            value={value || ''}
            onChange={(e) => onChange?.(e.target.value)}
            placeholder={placeholder}
            readOnly={readOnly}
        />
    ),
}))

const DRAFT_EXPERIMENT: ExperimentType = {
    ...NEW_EXPERIMENT,
    id: 123,
    name: 'Draft Experiment',
    type: 'product',
    metrics: [],
    saved_metrics: [],
    start_date: null as any,
    end_date: null as any,
    archived: false,
}

const apiMocks = {
    get: {
        '/api/projects/:team/experiments': () => [200, { results: [], count: 0 }],
        '/api/projects/:team/experiments/123': () => [200, DRAFT_EXPERIMENT],
        '/api/projects/:team/feature_flags/': () => [200, { results: [], count: 0 }],
        '/api/projects/:team/experiment_holdouts': () => [200, { results: [], count: 0 }],
        '/api/projects/:team/experiment_saved_metrics': () => [200, { results: [], count: 0 }],
        '/api/user_home_settings/@me/': () => [200, {}],
    },
    post: {
        '/api/environments/:team/query/': () => [200, { results: [] }],
    },
    patch: {
        '/api/environments/:team/add_product_intent/': () => [200, {}],
    },
}

function mockApiForExperiment(experimentData?: ExperimentType): Record<string, any> {
    return experimentData
        ? { ...apiMocks, get: { ...apiMocks.get, '/api/projects/:team/experiments/123': () => [200, experimentData] } }
        : apiMocks
}

function mountKeaLogics(): void {
    initKeaTests()
    featureFlagLogic.mount()
    featureFlagsLogic.mount()
    experimentsLogic.mount()
}

function cleanupKea(...logics: Array<{ unmount: () => void }>): void {
    cleanup()
    for (const logic of logics) {
        logic.unmount()
    }
    experimentsLogic.unmount()
    featureFlagsLogic.unmount()
    featureFlagLogic.unmount()
}

function renderExperimentViewPage(experimentData: ExperimentType): {
    sceneLogic: ReturnType<typeof experimentSceneLogic>
} {
    // Set the URL so urlToAction initializes correctly
    router.actions.push('/experiments/123')
    const sceneLogic = experimentSceneLogic({ experimentId: 123, formMode: FORM_MODES.update })
    sceneLogic.mount()
    sceneLogic.actions.setSceneState(123, FORM_MODES.update)
    sceneLogic.values.experimentLogicRef!.logic.actions.loadExperimentSuccess(experimentData)
    render(<Experiment />)
    return { sceneLogic }
}

beforeAll(() => {
    const modalRoot = document.createElement('div')
    modalRoot.setAttribute('id', 'root')
    document.body.appendChild(modalRoot)
})

describe('Experiment component', () => {
    it('commits manual results on the real metrics tab and stops observing when that tab is removed', async () => {
        localStorage.clear()
        sessionStorage.clear()
        const experimentData = {
            ...DRAFT_EXPERIMENT,
            start_date: '2024-01-01T00:00:00Z',
            status: ExperimentStatus.Running,
        }
        useMocks({
            ...mockApiForExperiment(experimentData),
            post: {
                '/api/environments/:team/query/:kind': () => [
                    200,
                    { timeseries: [], total_exposures: {}, is_cached: true },
                ],
            },
        })
        mountKeaLogics()
        featureFlagLogic.actions.setFeatureFlags([], {})
        const handle = { attemptId: '', firstUseful: jest.fn(), finish: jest.fn(), dispose: jest.fn() }
        jest.mocked(startCustomerJourney).mockImplementation((options) => ({
            ...handle,
            attemptId: options.attempt_id!,
        }))
        const { sceneLogic } = renderExperimentViewPage(experimentData)
        await waitFor(() => screen.getAllByText('Add primary metric'))
        const logic = sceneLogic.values.experimentLogicRef!.logic
        await act(async () => {
            await logic.asyncActions.refreshExperimentResults(true, 'manual', false, 'full_results_refresh')
        })
        expect(handle.finish).toHaveBeenCalledWith(
            'usable',
            expect.objectContaining({ total_count: 1, exposures_response_cached: true })
        )
        handle.finish.mockClear()
        let releaseExposures!: () => void
        const exposuresPending = new Promise<void>((resolve) => {
            releaseExposures = resolve
        })
        let requested = false
        useMocks({
            post: {
                '/api/environments/:team/query/:kind': async () => {
                    requested = true
                    await exposuresPending
                    return [200, { timeseries: [], total_exposures: {} }]
                },
            },
        })
        let refresh!: Promise<void>
        act(() => {
            refresh = logic.asyncActions.refreshExperimentResults(true, 'manual', false, 'full_results_refresh')
        })
        await waitFor(() => expect(requested).toBe(true))
        expect(handle.finish).not.toHaveBeenCalled()
        act(() => {
            sceneLogic.actions.setActiveTabKey('settings')
        })
        expect(handle.finish).toHaveBeenCalledWith('observation_stopped', expect.any(Object))
        await act(async () => {
            releaseExposures()
            await refresh
        })
        expect(handle.finish).toHaveBeenCalledTimes(1)
        jest.mocked(startCustomerJourney).mockClear()
        await act(async () => {
            await logic.asyncActions.refreshExperimentResults(true, 'manual', false, 'full_results_refresh')
        })
        expect(startCustomerJourney).not.toHaveBeenCalled()
        cleanupKea(sceneLogic)
        jest.mocked(startCustomerJourney).mockReset()
    })

    it('create mode shows wizard', async () => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks(apiMocks)
        mountKeaLogics()

        const createSceneLogic = experimentSceneLogic({ experimentId: 'new', formMode: FORM_MODES.create })
        createSceneLogic.mount()
        // Explicitly set create mode since urlToAction may override props default
        createSceneLogic.actions.setSceneState('new', FORM_MODES.create)

        render(<Experiment />)

        expect(screen.getByTestId('experiment-wizard')).toBeInTheDocument()
        cleanupKea(createSceneLogic)
    })

    it.each([
        {
            experimentOverrides: {},
            description: 'draft',
            expectLaunchButton: true,
            expectWarningBanner: false,
        },
        {
            experimentOverrides: {
                start_date: '2024-01-01T00:00:00Z',
                status: ExperimentStatus.Running,
            },
            description: 'running experiment',
            expectLaunchButton: false,
            expectWarningBanner: true,
        },
    ])(
        '$description without metrics shows add metric buttons',
        async ({ experimentOverrides, expectLaunchButton, expectWarningBanner }) => {
            const experimentData: ExperimentType = { ...DRAFT_EXPERIMENT, ...experimentOverrides }
            localStorage.clear()
            sessionStorage.clear()
            useMocks(mockApiForExperiment(experimentData))
            mountKeaLogics()

            const { sceneLogic } = renderExperimentViewPage(experimentData)

            await waitFor(() => {
                screen.getAllByText('Add primary metric')
            })
            screen.getAllByText('Add secondary metric')

            // No creation form should be shown in view mode
            expect(screen.queryByTestId('experiment-wizard')).not.toBeInTheDocument()

            if (expectLaunchButton) {
                const launchButton = document.querySelector('[data-attr="launch-experiment"]')
                expect(launchButton).toBeInTheDocument()
                // LemonButton sets aria-disabled={disabled}; React omits the attribute when false, or "false" when present
                expect(launchButton?.getAttribute('aria-disabled')).not.toBe('true')
            } else {
                expect(document.querySelector('[data-attr="launch-experiment"]')).not.toBeInTheDocument()
            }

            if (expectWarningBanner) {
                expect(screen.getByText('No metrics defined')).toBeInTheDocument()
            } else {
                expect(screen.queryByText('No metrics defined')).not.toBeInTheDocument()
            }

            cleanupKea(sceneLogic)
        }
    )
})
