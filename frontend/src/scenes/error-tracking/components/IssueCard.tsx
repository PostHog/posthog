import { IconBox, IconDocument, IconList } from '@posthog/icons'
import { LemonCard, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { mightHaveRecording } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconSubtitles, IconSubtitlesOff } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { match } from 'ts-pattern'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { Collapsible } from './Collapsible'
import { ContextDisplay } from './ContextDisplay'
import { ExceptionAttributesIconList } from './ExceptionAttributes/ExceptionAttributesIconList'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from './Stacktrace/StacktraceGenericDisplay'
import { StacktraceTextDisplay } from './Stacktrace/StacktraceTextDisplay'
import { ToggleButtonPrimitive } from './ToggleButton/ToggleButton'

export function IssueCard(): JSX.Element {
    const {
        propertiesLoading,
        firstSeen,
        issueLoading,
        properties,
        exceptionAttributes,
        additionalProperties,
        issue,
        sessionId,
        showStacktrace,
        showAllFrames,
        showContext,
        showAsText,
    } = useValues(errorTrackingIssueSceneLogic)
    const { setShowStacktrace, setShowAllFrames, setShowContext, setShowAsText } =
        useActions(errorTrackingIssueSceneLogic)
    const stacktraceDisplayProps = {
        className: cn('flex-grow', showContext ? 'w-2/3' : 'w-full'),
        truncateMessage: !showStacktrace,
        attributes: exceptionAttributes,
        showAllFrames,
        showAsText,
        issue,
        issueLoading,
        loading: propertiesLoading,
    }
    const contextDisplayProps = {
        className: cn(showContext && showStacktrace ? 'w-1/3 pl-2' : 'w-0'),
        attributes: exceptionAttributes,
        additionalProperties,
        showContext,
        loading: propertiesLoading,
    }
    return (
        <LemonCard hoverEffect={false} className="p-0 group p-2 px-3 relative overflow-hidden">
            <Collapsible
                isExpanded={showStacktrace && !propertiesLoading}
                className="pb-1 flex w-full"
                minHeight="calc(var(--spacing) * 12)"
            >
                <StacktraceIssueDisplay {...stacktraceDisplayProps} />
                <ContextDisplay {...contextDisplayProps} />
            </Collapsible>
            <IssueCardActions className="absolute top-2 right-3 flex gap-2 items-center z-10">
                <ButtonGroupPrimitive size="sm">
                    <ToggleButtonPrimitive
                        className="px-2"
                        checked={showStacktrace}
                        onCheckedChange={() => setShowStacktrace(!showStacktrace)}
                    >
                        {match(showStacktrace)
                            .with(false, () => (
                                <>
                                    <IconSubtitles />
                                    Show details
                                </>
                            ))
                            .with(true, () => (
                                <>
                                    <IconSubtitlesOff />
                                    Hide details
                                </>
                            ))
                            .exhaustive()}
                    </ToggleButtonPrimitive>
                    <ToggleButtonPrimitive
                        iconOnly
                        checked={showAsText}
                        onCheckedChange={setShowAsText}
                        tooltip="Show as text"
                    >
                        <IconDocument />
                    </ToggleButtonPrimitive>
                    <ToggleButtonPrimitive
                        iconOnly
                        checked={showAllFrames}
                        onCheckedChange={setShowAllFrames}
                        tooltip="Show vendor frames"
                    >
                        <IconBox />
                    </ToggleButtonPrimitive>
                    <ToggleButtonPrimitive
                        iconOnly
                        checked={showContext}
                        onCheckedChange={setShowContext}
                        tooltip="Show context"
                    >
                        <IconList />
                    </ToggleButtonPrimitive>
                </ButtonGroupPrimitive>
            </IssueCardActions>
            <div className="flex justify-between items-center pt-1">
                <EventPropertiesPreview />
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

function EventPropertiesPreview(): JSX.Element {
    const { exceptionAttributes, propertiesLoading } = useValues(errorTrackingIssueSceneLogic)
    return (
        <span className="flex items-center gap-1 text-muted group-hover:text-brand-red">
            {match(propertiesLoading)
                .with(true, () => (
                    <span className="text-muted space-x-2 text-xs">
                        <Spinner />
                        <span>Loading details...</span>
                    </span>
                ))
                .with(false, () => <ExceptionAttributesIconList attributes={exceptionAttributes!} />)
                .exhaustive()}
        </span>
    )
}

function IssueCardActions({
    children,
    onlyOnHover = false,
    className,
}: {
    children: React.ReactNode
    onlyOnHover?: boolean
    className?: string
}): JSX.Element {
    return (
        <div
            className={cn('flex justify-between items-center gap-1 bg-surface-primary', className, {
                'opacity-0 group-hover:opacity-100 transition-opacity': onlyOnHover,
            })}
            onClick={(e) => e.stopPropagation()}
        >
            {children}
        </div>
    )
}

function StacktraceIssueDisplay({
    showAsText,
    issue,
    issueLoading,
    ...stacktraceDisplayProps
}: {
    showAsText: boolean
    issue: ErrorTrackingRelationalIssue | null
    issueLoading: boolean
} & Omit<StacktraceBaseDisplayProps, 'renderLoading' | 'renderEmpty'>): JSX.Element {
    const Component = showAsText ? StacktraceTextDisplay : StacktraceGenericDisplay
    return (
        <Component
            {...stacktraceDisplayProps}
            renderLoading={(renderHeader) =>
                renderHeader({
                    type: issue?.name ?? undefined,
                    value: issue?.description ?? undefined,
                    loading: issueLoading,
                })
            }
            renderEmpty={() => <StacktraceEmptyDisplay />}
        />
    )
}
