import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { LearnFromSupportSetting } from './LearnFromSupportSetting'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('./businessKnowledgeSettingsLogic', () => ({
    businessKnowledgeSettingsLogic: {},
}))

describe('LearnFromSupportSetting', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({
            setLearnFromSupportEnabled: jest.fn(),
            loadSettings: jest.fn(),
        })
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'hides the switch while settings are loading',
            settings: null,
            settingsLoading: true,
            expectSwitch: false,
            expectSwitchDisabled: false,
            expectSupportLink: false,
            expectRetry: false,
        },
        {
            name: 'lets you retry when settings failed to load',
            settings: null,
            settingsLoading: false,
            expectSwitch: false,
            expectSwitchDisabled: false,
            expectSupportLink: false,
            expectRetry: true,
        },
        {
            name: 'disables the switch and links to Support settings when Support is off',
            settings: { learn_from_support_enabled: false, support_enabled: false },
            settingsLoading: false,
            expectSwitch: true,
            expectSwitchDisabled: true,
            expectSupportLink: true,
            expectRetry: false,
        },
        {
            name: 'lets you turn learning off when Support is off',
            settings: { learn_from_support_enabled: true, support_enabled: false },
            settingsLoading: false,
            expectSwitch: true,
            expectSwitchDisabled: false,
            expectSupportLink: true,
            expectRetry: false,
        },
    ])('$name', ({ settings, settingsLoading, expectSwitch, expectSwitchDisabled, expectSupportLink, expectRetry }) => {
        ;(useValues as jest.Mock).mockReturnValue({
            settings,
            settingsLoading,
            settingsSaving: false,
        })

        render(<LearnFromSupportSetting />)

        const switchEl = screen.queryByRole('switch')
        if (expectSwitch) {
            expect(switchEl).toBeInTheDocument()
            if (expectSwitchDisabled) {
                expect(switchEl).toBeDisabled()
            } else {
                expect(switchEl).not.toBeDisabled()
            }
        } else {
            expect(switchEl).not.toBeInTheDocument()
        }

        if (expectSupportLink) {
            expect(screen.getByRole('link')).toHaveAttribute('href', '/settings/environment-conversations')
        } else {
            expect(screen.queryByText('Turn on Support to learn from resolved tickets')).not.toBeInTheDocument()
        }

        if (expectRetry) {
            expect(screen.getByText('Try again')).toBeInTheDocument()
        } else {
            expect(screen.queryByText('Try again')).not.toBeInTheDocument()
        }
    })
})
