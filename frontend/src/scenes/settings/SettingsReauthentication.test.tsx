import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { Settings } from './Settings'
import { settingsSceneLogic } from './settingsSceneLogic'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('Settings re-authentication gate', () => {
    afterEach(() => {
        cleanup()
    })

    const renderSettingsScene = (path: string): void => {
        initKeaTests()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            sensitive_session_expires_at: dayjs().subtract(1, 'hour').toISOString(),
        })
        settingsSceneLogic().mount()
        router.actions.push(path)
        render(<Settings logicKey="settingsScene" handleLocally hideSections />)
    }

    it('does not gate feature previews behind re-authentication', async () => {
        renderSettingsScene('/settings/user-feature-previews')

        await waitFor(() => expect(screen.getByText('Feature previews')).toBeInTheDocument())
        expect(screen.queryByText('Re-authentication required')).not.toBeInTheDocument()
    })

    it('still gates personal API keys behind re-authentication', async () => {
        renderSettingsScene('/settings/user-api-keys')

        await waitFor(() => expect(screen.getByText('Re-authentication required')).toBeInTheDocument())
    })
})
