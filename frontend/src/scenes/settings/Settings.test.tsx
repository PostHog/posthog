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
        expect(screen.getAllByRole('button', { name: /try again/i }).length).toBeGreaterThan(0)
        expect(screen.queryByText(/not found/i)).not.toBeInTheDocument()
    })

    it('shows a loading state instead of "not found" while the project is still loading', async () => {
        useMocks({ get: { 'api/environments/@current': () => new Promise(() => {}) as any } })
        initKeaTests(true, null as any)
        renderSettingsScene()

        await waitFor(() => expect(document.querySelector('.Spinner')).toBeInTheDocument())
        expect(screen.queryByText(/not found/i)).not.toBeInTheDocument()
    })

    it('still shows "not found" for a section that does not exist', async () => {
        initKeaTests()
        settingsSceneLogic().mount()
        router.actions.push('/settings/project-not-a-real-section')
        render(<Settings logicKey="settingsScene" handleLocally hideSections />)

        await waitFor(() => expect(screen.getByText(/setting not found/i)).toBeInTheDocument())
    })
})
