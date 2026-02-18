import { BindLogic, useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { ActivityTab } from '~/types'

import { SessionDetailsCard } from './components/SessionDetailsCard'
import { SessionMetricsCard } from './components/SessionMetricsCard'
import { SessionRecordingSection } from './components/SessionRecordingSection'
import { SessionProfileLogicProps, sessionProfileLogic } from './sessionProfileLogic'

export const scene: SceneExport<SessionProfileLogicProps> = {
    component: SessionProfileScene,
    logic: sessionProfileLogic,
    paramsToProps: ({ params: { id } }) => ({ sessionId: decodeURIComponent(id) }),
}

export function SessionProfileScene(): JSX.Element {
    const { sessionId, sessionData, sessionDataLoading, eventsQuery } = useValues(sessionProfileLogic)
    const { loadSessionData } = useActions(sessionProfileLogic)

    if (!sessionData && !sessionDataLoading) {
        return <NotFound object="session" />
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
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => loadSessionData()}
                        loading={sessionDataLoading}
                    >
                        Refresh
                    </LemonButton>
                }
            />
            <SceneDivider />

            <BindLogic logic={sessionProfileLogic} props={{ sessionId }}>
                <div className="space-y-4">
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
                                {sessionData ? (
                                    <PersonDisplay
                                        person={{
                                            distinct_id: sessionData.distinct_id,
                                            properties: sessionData.person_properties || undefined,
                                        }}
                                        withIcon
                                    />
                                ) : (
                                    <LemonSkeleton className="h-4 w-32" />
                                )}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-muted-alt">Start time</div>
                            <div className="text-sm">
                                {sessionData ? (
                                    <TZLabel time={sessionData.start_timestamp} />
                                ) : (
                                    <LemonSkeleton className="h-4 w-24" />
                                )}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-muted-alt">End time</div>
                            <div className="text-sm">
                                {sessionData ? (
                                    <TZLabel time={sessionData.end_timestamp} />
                                ) : (
                                    <LemonSkeleton className="h-4 w-24" />
                                )}
                            </div>
                        </div>
                    </div>
                    <SessionMetricsCard />
                    <SessionDetailsCard />
                    <SessionRecordingSection />
                    <Query
                        uniqueKey="session-profile-events"
                        query={eventsQuery}
                        context={{
                            showOpenEditorButton: true,
                            extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                        }}
                    />
                </div>
            </BindLogic>
        </SceneContent>
    )
}
