import { IconChevronDown, IconWarning } from '@posthog/icons'
import { LemonCard, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { cn } from 'lib/utils/css-classes'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { cancelEvent } from '../utils'
import { Collapsible } from './Collapsible'
import { ContextDisplay } from './ContextDisplay'
import { StacktraceDisplay } from './StacktraceDisplay'

export function IssueCard(): JSX.Element {
    const { propertiesLoading, firstSeen, properties, sessionId, showStacktrace, showAllFrames, showContext } =
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
            <Collapsible isExpanded={showStacktrace} className="pb-2 flex w-full" minHeight="calc(var(--spacing) * 13)">
                <StacktraceDisplay
                    className={cn('flex-grow', {
                        'w-2/3': showContext,
                        'w-full': !showContext,
                    })}
                    truncateMessage={!showStacktrace}
                />
                <ContextDisplay
                    className={cn('', {
                        'w-1/3 pl-2': showContext,
                        'w-0': !showContext,
                    })}
                />
            </Collapsible>
            <div className="absolute top-2 right-3 flex gap-2 items-center">
                {
                    // We should timestamp from event properties here but for now only first seen event is accessible and data is not available
                    firstSeen && <TZLabel className="text-muted text-xs" time={firstSeen} />
                }
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
            {children}
        </div>
    )
}
