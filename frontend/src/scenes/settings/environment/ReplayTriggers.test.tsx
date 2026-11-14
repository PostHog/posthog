import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReplayTriggers } from './ReplayTriggers'
import { replayTriggersLogic } from './replayTriggersLogic'

describe('ReplayTriggers mobile tab', () => {
    const renderMobileTab = (v2Enabled: boolean): void => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.REPLAY_TRIGGERS_V2]: v2Enabled })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true })
        replayTriggersLogic.mount()
        replayTriggersLogic.actions.selectPlatform('mobile')
        render(<ReplayTriggers />)
    }

    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/': MOCK_DEFAULT_TEAM } })
    })

    afterEach(cleanup)

    it('shows the trigger groups editor when the flag is on', () => {
        renderMobileTab(true)

        expect(screen.getByText(/Trigger groups apply to every platform/)).toBeInTheDocument()
        expect(screen.getByText('Trigger groups')).toBeInTheDocument()
    })

    it('keeps the old banner and no editor when the flag is off', () => {
        renderMobileTab(false)

        expect(screen.getByText(/Trigger groups aren't available on mobile yet/)).toBeInTheDocument()
        expect(screen.queryByText(/Trigger groups apply to every platform/)).toBeNull()
        expect(screen.queryByText('Trigger groups')).toBeNull()
    })

    it.each(['Legacy recording conditions', 'Event emitted', 'Sample rate', 'Duration threshold'])(
        'keeps the legacy control "%s" visible when the flag is on',
        (label) => {
            renderMobileTab(true)

            expect(screen.getAllByText(new RegExp(label)).length).toBeGreaterThan(0)
        }
    )
})
