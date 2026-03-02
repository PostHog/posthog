import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment as ExperimentType } from '~/types'

import { NEW_EXPERIMENT } from './constants'
import { Experiment } from './Experiment'
import { FORM_MODES, experimentLogic } from './experimentLogic'
import { experimentSceneLogic } from './experimentSceneLogic'
import { experimentsLogic } from './experimentsLogic'

jest.mock('./ExperimentWizard/ExperimentWizard', () => ({
    ExperimentWizard: () => <div data-attr="experiment-wizard" />,
}))

jest.mock('./ExperimentForm', () => ({
    ExperimentForm: () => <div data-attr="experiment-classic-form" />,
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

const TAB_ID_CREATE = 'test-tab-create'
const TAB_ID_DRAFT = 'test-tab-draft'

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
        '/api/projects/:team/experiments/eligible_feature_flags/': () => [200, { results: [], count: 0 }],
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

beforeAll(() => {
    const modalRoot = document.createElement('div')
    modalRoot.setAttribute('id', 'root')
    document.body.appendChild(modalRoot)
})

describe('Experiment component routing', () => {
    it.each([
        {
            flagValue: 'test' as string | boolean,
            expectedFormTestId: 'experiment-wizard',
            description: 'wizard',
        },
        {
            flagValue: false as string | boolean,
            expectedFormTestId: 'experiment-classic-form',
            description: 'classic form',
        },
    ])('create mode shows $description', async ({ flagValue, expectedFormTestId }) => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks(apiMocks)
        initKeaTests()

        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.EXPERIMENTS_WIZARD_CREATION_FORM]: flagValue,
        })

        featureFlagsLogic.mount()
        experimentsLogic.mount()

        const createSceneLogic = experimentSceneLogic({
            tabId: TAB_ID_CREATE,
            experimentId: 'new',
            formMode: FORM_MODES.create,
        })
        createSceneLogic.mount()
        // Explicitly set create mode since urlToAction may override props default
        createSceneLogic.actions.setSceneState('new', FORM_MODES.create)

        render(<Experiment tabId={TAB_ID_CREATE} />)

        expect(screen.getByTestId(expectedFormTestId)).toBeInTheDocument()
        cleanup()
        createSceneLogic.unmount()

        experimentsLogic.unmount()
        featureFlagsLogic.unmount()
        featureFlagLogic.unmount()
    })

    it('draft without metrics shows view page with launch button', async () => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks(apiMocks)
        initKeaTests()

        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.EXPERIMENTS_WIZARD_CREATION_FORM]: 'test',
        })

        featureFlagsLogic.mount()
        experimentsLogic.mount()

        const draftSceneLogic = experimentSceneLogic({
            tabId: TAB_ID_DRAFT,
            experimentId: 123,
            formMode: FORM_MODES.update,
        })
        draftSceneLogic.mount()

        const expLogic = experimentLogic({
            experimentId: 123,
            formMode: FORM_MODES.update,
            tabId: TAB_ID_DRAFT,
        })
        expLogic.mount()
        expLogic.actions.loadExperimentSuccess(DRAFT_EXPERIMENT)

        render(<Experiment tabId={TAB_ID_DRAFT} />)

        await waitFor(() => {
            expect(document.querySelector('[data-attr="launch-experiment"]')).toBeInTheDocument()
        })
        expect(screen.queryByTestId('experiment-wizard')).not.toBeInTheDocument()
        expect(screen.queryByTestId('experiment-classic-form')).not.toBeInTheDocument()

        cleanup()
        expLogic.unmount()
        draftSceneLogic.unmount()

        experimentsLogic.unmount()
        featureFlagsLogic.unmount()
        featureFlagLogic.unmount()
    })

    it.each([
        {
            experimentOverrides: { start_date: '2024-01-01T00:00:00Z' },
            expectedHelpText: 'Add metrics to measure experiment results.',
            description: 'running experiment',
        },
        {
            experimentOverrides: {},
            expectedHelpText: 'Add at least one primary metric to launch an experiment.',
            description: 'draft',
        },
    ])('$description without metrics shows add metric buttons', async ({ experimentOverrides, expectedHelpText }) => {
        localStorage.clear()
        sessionStorage.clear()

        const experimentData: ExperimentType = {
            ...DRAFT_EXPERIMENT,
            ...experimentOverrides,
        }
        useMocks({
            ...apiMocks,
            get: {
                ...apiMocks.get,
                '/api/projects/:team/experiments/123': () => [200, experimentData],
            },
        })
        initKeaTests()

        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.EXPERIMENTS_WIZARD_CREATION_FORM]: 'test',
        })

        featureFlagsLogic.mount()
        experimentsLogic.mount()

        const tabId = 'test-tab-metrics'
        // Set the URL so urlToAction initializes correctly
        router.actions.push('/experiments/123')

        const sceneLogic = experimentSceneLogic({
            tabId,
            experimentId: 123,
            formMode: FORM_MODES.update,
        })
        sceneLogic.mount()
        sceneLogic.actions.setSceneState(123, FORM_MODES.update)

        const expLogicRef = sceneLogic.values.experimentLogicRef
        expLogicRef!.logic.actions.loadExperimentSuccess(experimentData)

        render(<Experiment tabId={tabId} />)

        await waitFor(() => {
            expect(screen.getByText('Add primary metric')).toBeInTheDocument()
        })
        expect(screen.getByText('Add secondary metric')).toBeInTheDocument()
        expect(screen.getByText(expectedHelpText, { exact: false })).toBeInTheDocument()

        cleanup()
        sceneLogic.unmount()

        experimentsLogic.unmount()
        featureFlagsLogic.unmount()
        featureFlagLogic.unmount()
    })
})
