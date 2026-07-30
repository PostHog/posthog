import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Settings } from './Settings'
import { settingsSceneLogic } from './settingsSceneLogic'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('Settings', () => {
    afterEach(() => {
        cleanup()
    })

    const renderSettingsScene = (): void => {
        settingsSceneLogic().mount()
        router.actions.push('/settings/project-replay')
        render(<Settings logicKey="settingsScene" handleLocally hideSections />)
    }

    it('shows a retry banner instead of "not found" when the project failed to load', async () => {
        useMocks({ get: { 'api/environments/@current': () => [500, { detail: 'nope' }] } })
        initKeaTests(true, null as any)
        renderSettingsScene()

        await waitFor(() => expect(screen.getByText(/couldn't load this project/i)).toBeInTheDocument())
        expect(screen.getAllByText(/try again/i).length).toBeGreaterThan(0)
        expect(screen.queryByText(/not found/i)).not.toBeInTheDocument()
    })

    it('shows a loading state instead of "not found" while the project is still loading', async () => {
        useMocks({
            get: {
                'api/environments/@current': async () => {
                    // Long enough to assert against the in-flight render, but it still resolves so
                    // the request doesn't outlive the test as a dangling handle.
                    await new Promise((resolve) => setTimeout(resolve, 2000))
                    return [200, MOCK_DEFAULT_TEAM]
                },
            },
        })
        initKeaTests(true, null as any)
        renderSettingsScene()

        await waitFor(() => expect(document.querySelector('.Spinner')).toBeInTheDocument())
        expect(screen.queryByText(/not found/i)).not.toBeInTheDocument()
    })

    it('points an organization with no projects at project creation rather than a retry', async () => {
        // sceneLogic lets /settings through for a user with no projects, so this state is reachable
        // and a "try again" there would loop forever against a project that does not exist.
        useMocks({ get: { 'api/environments/@current': () => [404, { detail: 'not found' }] } })
        initKeaTests(true, null as any, undefined, { ...MOCK_DEFAULT_ORGANIZATION, teams: [] })
        renderSettingsScene()

        await waitFor(() => expect(screen.getByText(/doesn't have a project yet/i)).toBeInTheDocument())
        expect(screen.queryByText(/try again/i)).not.toBeInTheDocument()
    })

    it('still shows "not found" for a section that does not exist', async () => {
        initKeaTests()
        settingsSceneLogic().mount()
        router.actions.push('/settings/project-not-a-real-section')
        render(<Settings logicKey="settingsScene" handleLocally hideSections />)

        await waitFor(() => expect(screen.getByText(/setting not found/i)).toBeInTheDocument())
    })
})
