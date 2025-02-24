import { LemonCollapse, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import PanelLayout, { SettingsButton } from 'lib/components/PanelLayout/PanelLayout'
import { useState } from 'react'

import { ErrorTrackingFilters } from '../ErrorTrackingFilters'
import { errorTrackingIssueSceneLogic, EventsMode } from '../errorTrackingIssueSceneLogic'
import { getExceptionAttributes, hasStacktrace } from '../utils'
import { Overview } from './Overview'
import RecordingPanel from './panels/RecordingPanel'
import StackTracePanel from './panels/StacktracePanel'
import { EventsTab } from './tabs/EventsTab'

export type ErrorTrackingIssueEventsPanel = {
    key: 'stacktrace' | 'recording'
    Content: () => JSX.Element
    Header: string | (({ active }: { active: boolean }) => JSX.Element)
    hasContent: ({ hasStack, hasRecording }: { hasStack: boolean; hasRecording: boolean }) => boolean
    className?: string
}

const PANELS = [StackTracePanel, RecordingPanel] as ErrorTrackingIssueEventsPanel[]

export const Events = (): JSX.Element => {
    const { issueProperties, eventsMode } = useValues(errorTrackingIssueSceneLogic)
    const { setEventsMode } = useActions(errorTrackingIssueSceneLogic)
    const [activeKeys, setActiveKeys] = useState<ErrorTrackingIssueEventsPanel['key'][]>(['stacktrace'])

    const { exceptionList } = getExceptionAttributes(issueProperties)

    const hasStack = hasStacktrace(exceptionList)
    const hasRecording = issueProperties['$session_id'] && issueProperties['$recording_status'] === 'active'

    const panels = PANELS.filter(({ hasContent }) => hasContent({ hasStack, hasRecording })).map(
        ({ key, Header, Content, className }) => ({
            key,
            content: <Content />,
            header: typeof Header === 'string' ? Header : <Header active={activeKeys.includes(key)} />,
            className,
        })
    )

    return (
        <>
            <PanelLayout.PanelSettings title="Events" border="bottom">
                {/* TODO: follow up PR when we support this in the events query */}
                {/* {eventsMode != EventsMode.All && (
                    <SettingsMenu
                        highlightWhenActive={false}
                        items={[
                            {
                                label: 'Earliest',
                                onClick: () => setEventsMode(EventsMode.Earliest),
                                active: eventsMode === EventsMode.Earliest,
                            },
                            {
                                label: 'Latest',
                                onClick: () => setEventsMode(EventsMode.Latest),
                                active: eventsMode === EventsMode.Latest,
                            },
                            {
                                label: 'Recommended',
                                onClick: () => setEventsMode(EventsMode.Recommended),
                                active: eventsMode === EventsMode.Recommended,
                            },
                        ]}
                        label={capitalizeFirstLetter(eventsMode)}
                    />
                )} */}
                <SettingsButton
                    label={eventsMode === EventsMode.All ? 'Close' : 'View all events'}
                    active
                    onClick={() => setEventsMode(eventsMode === EventsMode.All ? EventsMode.Latest : EventsMode.All)}
                />
            </PanelLayout.PanelSettings>
            {eventsMode === EventsMode.All ? (
                <div className="m-4">
                    <ErrorTrackingFilters />
                    <LemonDivider thick className="mt-2 mb-0" />
                    <EventsTab />
                </div>
            ) : (
                <>
                    <Overview />
                    <LemonDivider className="mt-2 mb-0" />
                    {panels.length > 0 && (
                        <LemonCollapse
                            embedded
                            multiple
                            activeKeys={activeKeys}
                            onChange={setActiveKeys}
                            panels={panels}
                        />
                    )}
                </>
            )}
        </>
    )
}
