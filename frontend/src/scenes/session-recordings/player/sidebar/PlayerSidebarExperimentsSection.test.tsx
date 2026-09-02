import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    ENROLLED_CURRENT_EXPERIMENT_ID,
    experimentSessionContextEnrolledCurrentResponse,
} from '../../__mocks__/experiment_session_context'
import { setupSessionRecordingTest } from '../__mocks__/test-setup'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarExperimentsSection } from './PlayerSidebarExperimentsSection'

describe('PlayerSidebarExperimentsSection', () => {
    const logicProps = {
        sessionRecordingId: experimentSessionContextEnrolledCurrentResponse.session_id,
        playerKey: 'experiments-section-test',
    }

    beforeEach(() => {
        setupSessionRecordingTest({
            getMocks: {
                '/api/projects/:team_id/experiments/session_context/': experimentSessionContextEnrolledCurrentResponse,
            },
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT], {
            [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT]: true,
        })
    })

    // Pinning lifts the arrived-from experiment out of the enrolled group, and so out of that group's
    // label. Without a marker of its own the row claims an exposure this session has no event for.
    it('says the pinned experiment was not exposed when the session has no exposure event for it', async () => {
        router.actions.push(urls.experiment(ENROLLED_CURRENT_EXPERIMENT_ID))

        render(
            <Provider>
                <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                    <PlayerSidebarExperimentsSection />
                </BindLogic>
            </Provider>
        )

        expect(await screen.findByText('Not exposed in this session')).toBeInTheDocument()
    })
})
