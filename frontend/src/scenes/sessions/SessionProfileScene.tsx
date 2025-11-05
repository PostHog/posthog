import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { humanFriendlyDuration } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { RecordingEventType } from '~/types'

import { SessionProfileLogicProps, sessionProfileLogic } from './sessionProfileLogic'

export const scene: SceneExport<SessionProfileLogicProps> = {
    component: SessionProfileScene,
    logic: sessionProfileLogic,
    paramsToProps: ({ params: { id } }) => ({ sessionId: decodeURIComponent(id) }),
}

export function SessionProfileScene(): JSX.Element {
    const { sessionData, sessionEvents, sessionDuration, uniqueUrlCount, totalEventCount, isLoading } =
        useValues(sessionProfileLogic)
    const { loadSessionData } = useActions(sessionProfileLogic)

    console.log('JFBW: sessionData', sessionData)
    console.log('JFBW: sessionData', sessionData)
    if (!sessionData && !isLoading) {
        return <NotFound object="session" />
    }

    if (isLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Session profile"
                resourceType={{
                    type: sceneConfigurations[Scene.SessionProfile].iconType || 'default_icon_type',
                }}
            />
            <SceneDivider />

            <div className="space-y-4">
                <div className="flex items-center gap-2">
                    <span className="text-secondary font-semibold">Session ID:</span>
                    <LemonTag type="success">{sessionData?.session_id}</LemonTag>
                </div>

                <div className="border border-border rounded p-6 bg-bg-light">
                    <h3 className="text-lg font-semibold mb-4">Session details</h3>
                    <div className="space-y-2">
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Session ID:</span>
                            <span className="font-mono">{sessionData?.session_id}</span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Start time:</span>
                            {sessionData?.start_timestamp ? (
                                <TZLabel time={sessionData.start_timestamp} />
                            ) : (
                                <span>-</span>
                            )}
                        </div>
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">End time:</span>
                            {sessionData?.end_timestamp ? <TZLabel time={sessionData.end_timestamp} /> : <span>-</span>}
                        </div>
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Duration:</span>
                            <span>
                                {sessionDuration !== null
                                    ? `${humanFriendlyDuration(sessionDuration)} (${sessionDuration} seconds)`
                                    : '-'}
                            </span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Events:</span>
                            <span>
                                {totalEventCount} events ({sessionData?.pageview_count || 0} pageviews,{' '}
                                {sessionData?.autocapture_count || 0} autocapture, {sessionData?.screen_count || 0}{' '}
                                screens)
                            </span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Unique URLs:</span>
                            <span>{uniqueUrlCount}</span>
                        </div>
                        {sessionData?.channel_type && (
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">Channel type:</span>
                                <LemonTag>{sessionData.channel_type}</LemonTag>
                            </div>
                        )}
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Is bounce:</span>
                            <LemonTag type={sessionData?.is_bounce ? 'warning' : 'success'}>
                                {sessionData?.is_bounce ? 'Yes' : 'No'}
                            </LemonTag>
                        </div>
                    </div>
                </div>

                <div className="border border-border rounded p-6 bg-bg-light">
                    <h3 className="text-lg font-semibold mb-4">User information</h3>
                    <div className="space-y-2">
                        <div className="flex gap-2">
                            <span className="text-secondary min-w-32">Distinct ID:</span>
                            <span className="font-mono">{sessionData?.distinct_id || '-'}</span>
                        </div>
                        {sessionData?.entry_hostname && (
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">Hostname:</span>
                                <span>{sessionData.entry_hostname}</span>
                            </div>
                        )}
                        {sessionData?.entry_pathname && (
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">Entry path:</span>
                                <span>{sessionData.entry_pathname}</span>
                            </div>
                        )}
                    </div>
                </div>

                {(sessionData?.entry_utm_source ||
                    sessionData?.entry_utm_campaign ||
                    sessionData?.entry_referring_domain) && (
                    <div className="border border-border rounded p-6 bg-bg-light">
                        <h3 className="text-lg font-semibold mb-4">Attribution</h3>
                        <div className="space-y-2">
                            {sessionData?.entry_referring_domain && (
                                <div className="flex gap-2">
                                    <span className="text-secondary min-w-32">Referring domain:</span>
                                    <span>{sessionData.entry_referring_domain}</span>
                                </div>
                            )}
                            {sessionData?.entry_utm_source && (
                                <div className="flex gap-2">
                                    <span className="text-secondary min-w-32">UTM source:</span>
                                    <span>{sessionData.entry_utm_source}</span>
                                </div>
                            )}
                            {sessionData?.entry_utm_campaign && (
                                <div className="flex gap-2">
                                    <span className="text-secondary min-w-32">UTM campaign:</span>
                                    <span>{sessionData.entry_utm_campaign}</span>
                                </div>
                            )}
                            {sessionData?.entry_utm_medium && (
                                <div className="flex gap-2">
                                    <span className="text-secondary min-w-32">UTM medium:</span>
                                    <span>{sessionData.entry_utm_medium}</span>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                <div className="border border-border rounded p-6 bg-bg-light">
                    <h3 className="text-lg font-semibold mb-4">URLs</h3>
                    <div className="space-y-2">
                        {sessionData?.entry_current_url && (
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">Entry URL:</span>
                                <span className="truncate">{sessionData.entry_current_url}</span>
                            </div>
                        )}
                        {sessionData?.end_current_url && (
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">Exit URL:</span>
                                <span className="truncate">{sessionData.end_current_url}</span>
                            </div>
                        )}
                        {sessionData?.last_external_click_url && (
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">Last external click:</span>
                                <span className="truncate">{sessionData.last_external_click_url}</span>
                            </div>
                        )}
                    </div>
                </div>

                <div className="border border-border rounded p-6 bg-bg-light">
                    <h3 className="text-lg font-semibold mb-4">Events ({sessionEvents?.length || 0})</h3>
                    <div className="space-y-1 max-h-96 overflow-y-auto">
                        {sessionEvents?.map((event: RecordingEventType) => (
                            <div key={event.id} className="text-sm flex gap-2 border-b border-border pb-1">
                                <TZLabel time={event.timestamp} className="text-xs text-muted-alt min-w-32" />
                                <span className="font-semibold">{event.event}</span>
                                {event.properties?.$current_url && (
                                    <span className="text-muted-alt truncate">- {event.properties.$current_url}</span>
                                )}
                            </div>
                        ))}
                        {(!sessionEvents || sessionEvents.length === 0) && (
                            <div className="text-muted-alt">No events found</div>
                        )}
                    </div>
                </div>

                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={() => loadSessionData()}>
                        Refresh
                    </LemonButton>
                </div>
            </div>
        </SceneContent>
    )
}
