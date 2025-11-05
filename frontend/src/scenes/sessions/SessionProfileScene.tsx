import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
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
    const { sessionData, sessionEvents, sessionDuration, uniqueUrlCount, totalEventCount, isLoading } =
        useValues(sessionProfileLogic)
    const { loadSessionData, loadEventDetails } = useActions(sessionProfileLogic)

    if (!sessionData && !isLoading) {
        return <NotFound object="session" />
    }

    if (isLoading) {
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
                    <LemonButton type="secondary" onClick={() => loadSessionData()}>
                        Refresh
                    </LemonButton>
                }
            />
            <SceneDivider />

            <div className="space-y-4">
                {sessionData && (
                    <div className="flex flex-wrap gap-x-6 gap-y-2">
                        <div>
                            <div className="text-xs text-muted-alt">Session ID</div>
                            <div className="font-mono text-sm">{sessionData.session_id}</div>
                        </div>
                        <div>
                            <div className="text-xs text-muted-alt">Person</div>
                            <div className="text-sm">
                                <PersonDisplay person={{ distinct_id: sessionData.distinct_id }} withIcon />
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

                <SessionMetricsCard
                    duration={sessionDuration}
                    uniqueUrlCount={uniqueUrlCount}
                    totalEventCount={totalEventCount}
                    pageviewCount={sessionData?.pageview_count}
                    autocaptureCount={sessionData?.autocapture_count}
                    screenCount={sessionData?.screen_count}
                    isLoading={isLoading}
                />

                <SessionDetailsCard sessionData={sessionData} isLoading={isLoading} />

                <SessionEventsList events={sessionEvents} isLoading={isLoading} onLoadEventDetails={loadEventDetails} />
            </div>
        </SceneContent>
    )
}
