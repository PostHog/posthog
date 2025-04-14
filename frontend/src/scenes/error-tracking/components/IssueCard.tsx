import { IconChevronDown, IconWarning } from '@posthog/icons'
import { LemonCard, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { mightHaveRecording } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { cn } from 'lib/utils/css-classes'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
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
            <Collapsible
                isExpanded={showStacktrace && !propertiesLoading}
                className="pb-2 flex w-full"
                minHeight="calc(var(--spacing) * 13)"
            >
                <StacktraceDisplay
                    className={cn('flex-grow', showContext ? 'w-2/3' : 'w-full')}
                    truncateMessage={!showStacktrace}
                />
                <ContextDisplay className={cn('', showContext ? 'w-1/3 pl-2' : 'w-0')} />
            </Collapsible>
            <IssueCardActions className="absolute top-2 right-3 flex gap-2 items-center">
                <LemonSwitch
                    id="show-all-frames"
                    label="Show all frames"
                    checked={showAllFrames}
                    size="xsmall"
                    bordered
                    onChange={setShowAllFrames}
                    className="select-none"
                />
                <LemonSwitch
                    id="show-context"
                    label="Show context"
                    checked={showContext}
                    size="xsmall"
                    bordered
                    onChange={setShowContext}
                    className="select-none"
                />
            </IssueCardActions>
            <div className="flex justify-between items-center">
                <StacktraceExpander />
                <IssueCardActions>
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
                        disabledReason={mightHaveRecording(properties) ? undefined : 'No recording available'}
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
                .otherwise(() => null)}
        </span>
    )
}

function IssueCardActions({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    return (
        <div className={cn('flex justify-between items-center gap-1', className)} onClick={(e) => e.stopPropagation()}>
            {children}
        </div>
    )
}
