import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

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

describe('Experiment form type consistency', () => {
    it.each([
        {
            flagValue: 'test' as string | boolean,
            expectedTestId: 'experiment-wizard',
            description: 'wizard',
        },
        {
            flagValue: false as string | boolean,
            expectedTestId: 'experiment-classic-form',
            description: 'classic form',
        },
    ])(
        'create mode and draft-without-metrics view mode both show $description',
        async ({ flagValue, expectedTestId }) => {
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

            // --- Test create mode ---
            // Pre-mount the scene logic so Experiment component reads the right formMode
            const createSceneLogic = experimentSceneLogic({
                tabId: TAB_ID_CREATE,
                experimentId: 'new',
                formMode: FORM_MODES.create,
            })
            createSceneLogic.mount()

            render(<Experiment tabId={TAB_ID_CREATE} />)

            expect(screen.getByTestId(expectedTestId)).toBeInTheDocument()
            cleanup()
            createSceneLogic.unmount()

            // --- Test draft-without-metrics view mode ---
            // Pre-mount the scene logic and experiment logic for the draft experiment
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
                expect(screen.getByTestId(expectedTestId)).toBeInTheDocument()
            })

            cleanup()
            expLogic.unmount()
            draftSceneLogic.unmount()

            experimentsLogic.unmount()
            featureFlagsLogic.unmount()
            featureFlagLogic.unmount()
        }
    )
})
