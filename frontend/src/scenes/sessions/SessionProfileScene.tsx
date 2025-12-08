import { BindLogic, useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ActivityTab } from '~/types'

import { SessionDetailsCard } from './components/SessionDetailsCard'
import { SessionEventsList } from './components/SessionEventsList'
import { SessionMetricsCard } from './components/SessionMetricsCard'
import { SessionProfileLogicProps, sessionProfileLogic } from './sessionProfileLogic'

export const scene: SceneExport<SessionProfileLogicProps> = {
    component: SessionProfileScene,
    logic: sessionProfileLogic,
    paramsToProps: ({ params: { id } }) => ({ sessionId: decodeURIComponent(id) }),
}

export function SessionProfileScene(): JSX.Element {
    const {
        sessionId,
        sessionData,
        isInitialLoading,
        sessionDataLoading,
        sessionEventsLoading,
        hasRecording,
        hasRecordingLoading,
    } = useValues(sessionProfileLogic)
    const { loadSessionData } = useActions(sessionProfileLogic)

    if (!sessionData && !isInitialLoading) {
        return <NotFound object="session" />
    }

    if (isInitialLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Session Profile"
                resourceType={{
                    type: sceneConfigurations[Scene.SessionProfile].iconType || 'default_icon_type',
                }}
                forceBackTo={{
                    name: sceneConfigurations[Scene.ExploreSessions].name,
                    path: urls.activity(ActivityTab.ExploreSessions),
                    key: 'sessions',
                }}
                actions={
                    <>
                        <ViewRecordingButton
                            sessionId={sessionData?.session_id}
                            recordingStatus={hasRecording ? 'active' : 'none'}
                            inModal={true}
                            size="small"
                            type="secondary"
                            loading={hasRecordingLoading}
                        />
                        <LemonButton
                            type="secondary"
                            icon={<IconRefresh />}
                            onClick={() => loadSessionData()}
                            loading={sessionDataLoading || sessionEventsLoading}
                        >
                            Refresh
                        </LemonButton>
                    </>
                }
            />
            <SceneDivider />

            <BindLogic logic={sessionProfileLogic} props={{ sessionId }}>
                <div className="space-y-4">
                    {sessionData && (
                        <div className="flex flex-wrap gap-x-6 gap-y-2">
                            <div>
                                <div className="text-xs text-muted-alt">Session ID</div>
                                <div className="font-mono text-sm">
                                    <CopyToClipboardInline description="session ID">{sessionId}</CopyToClipboardInline>
                                </div>
                            </div>
                            <div>
                                <div className="text-xs text-muted-alt">Person</div>
                                <div className="text-sm">
                                    <PersonDisplay
                                        person={{
                                            distinct_id: sessionData.distinct_id,
                                            properties: sessionData.person_properties || undefined,
                                        }}
                                        withIcon
                                    />
                                </div>
                            </div>
                            <div>
                                <div className="text-xs text-muted-alt">Start time</div>
                                <div className="text-sm">
                                    <TZLabel time={sessionData.start_timestamp} />
                                </div>
                            </div>
                            <div>
                                <div className="text-xs text-muted-alt">End time</div>
                                <div className="text-sm">
                                    <TZLabel time={sessionData.end_timestamp} />
                                </div>
                            </div>
                        </div>
                    )}
                    <SessionMetricsCard />
                    <SessionDetailsCard />
                    <SessionEventsList />
                </div>
            </BindLogic>
        </SceneContent>
    )
}
