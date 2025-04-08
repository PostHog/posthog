import { IconChevronDown, IconWarning } from '@posthog/icons'
import { LemonCard, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { cn } from 'lib/utils/css-classes'
import { Children, Fragment } from 'react'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { cancelEvent } from '../utils'
import { Collapsible } from './Collapsible'
import { ContextDisplay } from './ContextDisplay'
import { StacktraceDisplay } from './StacktraceDisplay'

export function IssueCard(): JSX.Element {
    const { propertiesLoading, properties, sessionId, showStacktrace, showAllFrames, showContext } =
        useValues(errorTrackingIssueSceneLogic)
    const { setShowStacktrace, setShowAllFrames, setShowContext } = useActions(errorTrackingIssueSceneLogic)
    return (
        <LemonCard
            hoverEffect={false}
            className="p-0 group cursor-pointer p-2 px-3 relative"
            onClick={() => {
                setShowStacktrace(!showStacktrace)
            }}
        >
            <Collapsible isExpanded={showStacktrace} className="pb-2 flex" minHeight="calc(var(--spacing) * 13)">
                <StacktraceDisplay className="flex-grow" />
                <ContextDisplay />
            </Collapsible>
            <div className="absolute top-2 right-3 flex gap-2">
                <ViewRecordingButton
                    sessionId={sessionId}
                    timestamp={properties.timestamp}
                    loading={propertiesLoading}
                    inModal={true}
                    size="xsmall"
                    type="secondary"
                    disabledReason={sessionId ? undefined : 'No recording available'}
                />
            </div>
            <div className="flex justify-between items-center">
                <StacktraceExpander />
                <IssueCardActions>
                    <LemonSwitch
                        label="Show all frames"
                        checked={showAllFrames}
                        size="xsmall"
                        bordered
                        onChange={setShowAllFrames}
                    />
                    <LemonSwitch
                        label="Show context"
                        checked={showContext}
                        size="xsmall"
                        bordered
                        onChange={setShowContext}
                    />
                </IssueCardActions>
            </div>
        </LemonCard>
    )
}

function StacktraceExpander(): JSX.Element {
    const { showStacktrace, propertiesLoading, hasStacktrace } = useValues(errorTrackingIssueSceneLogic)
    return (
        <span className="flex items-center gap-1 text-muted group-hover:text-brand-red">
            {match([propertiesLoading, hasStacktrace])
                .with([true, P.any], () => (
                    <span className="text-muted space-x-2 text-xs">
                        <Spinner />
                        <span>Loading stacktrace...</span>
                    </span>
                ))
                .with([false, false], () => (
                    <>
                        <IconWarning />
                        No stacktrace available
                    </>
                ))
                .with([false, true], () => (
                    <>
                        <span className="text-xs">{showStacktrace ? 'Hide details' : 'Show details'}</span>
                        <IconChevronDown
                            className={cn('transition-transform duration-300', {
                                'rotate-180': showStacktrace,
                            })}
                        />
                    </>
                ))
                .exhaustive()}
        </span>
    )
}

function IssueCardActions({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between items-center gap-1" onClick={cancelEvent}>
            {Children.toArray(children)
                .filter((child) => !!child)
                .map((child, index) => (
                    <Fragment key={index}>
                        {child}
                        {/* {index !== array.length - 1 && (
                            <LemonDivider vertical={true} className="h-3 mx-1 self-center" />
                        )} */}
                    </Fragment>
                ))}
        </div>
    )
}
