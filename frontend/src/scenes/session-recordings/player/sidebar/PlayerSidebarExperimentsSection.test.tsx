import '@testing-library/jest-dom'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import type { ExperimentSessionContextResponseApi } from 'products/experiments/frontend/generated/api.schemas'

import {
    ENROLLED_CURRENT_EXPERIMENT_ID,
    experimentSessionContextEnrolledCurrentResponse,
    makeExperimentSessionContextItem,
} from '../../__mocks__/experiment_session_context'
import { setupSessionRecordingTest } from '../__mocks__/test-setup'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { computeExposureSeek, PlayerSidebarExperimentsSection } from './PlayerSidebarExperimentsSection'

describe('PlayerSidebarExperimentsSection', () => {
    describe('computeExposureSeek', () => {
        const START = 1_000_000
        const END = 1_100_000

        // The recorder boots after or stops before the exposure event, so the exposure lands outside
        // the captured frames. Each case pins the sign of the offset and the frame the jump lands on.
        it.each([
            ['before the first frame', 997_000, END, -3_000, 'before', START],
            ['inside the window', 1_040_000, END, 40_000, 'inside', 1_040_000],
            ['after the last frame', 1_112_000, END, 12_000, 'after', END],
            ['exactly on the last frame stays in window', END, END, 100_000, 'inside', END],
            ['with an unknown end stays in window', 1_200_000, null, 200_000, 'inside', 1_200_000],
        ])('places an exposure %s', (_label, exposedAtMs, endMs, offsetMs, placement, seekTargetMs) => {
            expect(computeExposureSeek(exposedAtMs, START, endMs as number | null)).toEqual({
                offsetMs,
                placement,
                seekTargetMs,
            })
        })
    })

    describe('rendering', () => {
        beforeEach(() => {
            setupSessionRecordingTest({
                getMocks: {
                    '/api/projects/:team_id/experiments/session_context/':
                        experimentSessionContextEnrolledCurrentResponse,
                },
            })
        })

        // Pinning lifts the arrived-from experiment out of the enrolled group, and so out of that
        // group's label. Without a marker of its own the row claims an exposure this session has no
        // event for.
        it('says the pinned experiment was not exposed when the session has no exposure event for it', async () => {
            router.actions.push(urls.experiment(ENROLLED_CURRENT_EXPERIMENT_ID))

            render(
                <Provider>
                    <BindLogic
                        logic={sessionRecordingPlayerLogic}
                        props={{
                            sessionRecordingId: experimentSessionContextEnrolledCurrentResponse.session_id,
                            playerKey: 'experiments-section-test',
                        }}
                    >
                        <PlayerSidebarExperimentsSection />
                    </BindLogic>
                </Provider>
            )

            expect(await screen.findByText('Not exposed in this session')).toBeInTheDocument()
        })

        // The playable window runs from 14:46:20.877 for the recording's 11s duration, which ends
        // ahead of the metadata's end_time (see the recording_meta and recording_snapshots mocks).
        // An exposure outside it used to render a grey, unclickable 00:00; it must now be a signed
        // offset that jumps to the closest captured frame.
        it('renders an out-of-window exposure as a signed, seekable offset', async () => {
            const sessionRecordingId = 'experiment-context-out-of-window'
            const response: ExperimentSessionContextResponseApi = {
                session_id: sessionRecordingId,
                results: [
                    makeExperimentSessionContextItem({
                        experiment_id: 301,
                        experiment_name: 'Before start',
                        first_exposure_timestamp: '2023-05-01T14:45:57.000000Z',
                    }),
                    makeExperimentSessionContextItem({
                        experiment_id: 302,
                        experiment_name: 'Inside window',
                        first_exposure_timestamp: '2023-05-01T14:46:26.000000Z',
                    }),
                    makeExperimentSessionContextItem({
                        experiment_id: 303,
                        experiment_name: 'After end',
                        first_exposure_timestamp: '2023-05-01T14:47:10.000000Z',
                    }),
                    makeExperimentSessionContextItem({
                        experiment_id: 304,
                        experiment_name: 'Fraction of a second before start',
                        first_exposure_timestamp: '2023-05-01T14:46:20.577000Z',
                    }),
                ],
            }
            setupSessionRecordingTest({
                getMocks: { '/api/projects/:team_id/experiments/session_context/': response },
            })
            // Only /experiments/<id> pins a row; a neutral path keeps them all inline.
            router.actions.push('/replay')

            const logicProps = { sessionRecordingId, playerKey: 'oow-test' }
            render(
                <Provider>
                    <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                        <PlayerSidebarExperimentsSection />
                    </BindLogic>
                </Provider>
            )

            // The exposure column appears only once the window resolves, so wait for the jump link.
            const exposureLink = async (experimentName: string): Promise<HTMLElement> => {
                const row = (await screen.findByText(experimentName)).parentElement as HTMLElement
                return waitFor(() => {
                    const link = row.querySelector<HTMLElement>(
                        '[data-attr="replay-experiment-context-jump-to-first-exposure"]'
                    )
                    expect(link).not.toBeNull()
                    return link as HTMLElement
                })
            }

            const before = await exposureLink('Before start')
            // An interactive control, not the grey span the out-of-window case used to render. Link
            // with an onClick and no `to` renders a button.
            expect(before.tagName).toBe('BUTTON')
            expect(before.textContent).toBe('-00:24')
            expect((await exposureLink('Inside window')).textContent).toBe('00:05')
            const after = await exposureLink('After end')
            expect(after.textContent).toBe('+00:39')
            // A gap under a second rounds up rather than flooring to 00:00, which would read as the
            // "no exposure here" the signed offset exists to correct.
            expect((await exposureLink('Fraction of a second before start')).textContent).toBe('-00:01')

            // Wiring the jump to the wrong field would pass the helper cases and the label
            // assertions alike, so the click has to land on the closest captured frame itself.
            const logic = sessionRecordingPlayerLogic(logicProps)
            const { start, durationMs } = logic.values.sessionPlayerData
            // The playable window ends a duration after the start, which can precede the metadata's
            // end_time, so the last frame is derived the way the section bounds the window.
            const firstFrameMs = start?.valueOf() as number
            const lastFrameMs = firstFrameMs + durationMs

            fireEvent.click(before)
            await expectLogic(logic).toDispatchActions([
                (action) =>
                    action.type === logic.actionTypes.seekToTimestamp && action.payload.timestamp === firstFrameMs,
            ])

            fireEvent.click(after)
            await expectLogic(logic).toDispatchActions([
                (action) =>
                    action.type === logic.actionTypes.seekToTimestamp && action.payload.timestamp === lastFrameMs,
            ])
        })
    })
})
