import { LemonCollapse, LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import PanelLayout from 'lib/components/PanelLayout/PanelLayout'
import { useState } from 'react'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { Overview } from './Overview'
import RecordingPanel from './panels/RecordingPanel'
import StacktracePanel from './panels/StacktracePanel'

export type ErrorTrackingIssueEventsPanel = {
    key: 'stacktrace' | 'recording'
    Content: () => JSX.Element
    EmptyState: () => JSX.Element
    Header: string | (({ active }: { active: boolean }) => JSX.Element)
    hasContent: ({
        issueProperties,
        exceptionList,
    }: {
        issueProperties: Record<string, any>
        exceptionList: ErrorTrackingException[]
    }) => boolean
    className?: string
}

const PANELS = [StacktracePanel, RecordingPanel] as ErrorTrackingIssueEventsPanel[]

export const Events = (): JSX.Element => {
    const { issueProperties, exceptionList } = useValues(errorTrackingIssueSceneLogic)
    const [activeKeys, setActiveKeys] = useState<ErrorTrackingIssueEventsPanel['key'][]>(['stacktrace'])

    const panels = PANELS.map(({ key, hasContent, Header, Content, EmptyState, ...props }) => ({
        key,
        header: typeof Header === 'string' ? Header : <Header active={activeKeys.includes(key)} />,
        content: !hasContent || hasContent({ issueProperties, exceptionList }) ? <Content /> : <EmptyState />,
        ...props,
    }))

    return (
        <>
            <PanelLayout.PanelSettings title="Events" border="bottom" />
            <Overview />
            <LemonDivider className="mt-2 mb-0" />
            <LemonCollapse embedded multiple activeKeys={activeKeys} onChange={setActiveKeys} panels={panels} />
        </>
    )
}
