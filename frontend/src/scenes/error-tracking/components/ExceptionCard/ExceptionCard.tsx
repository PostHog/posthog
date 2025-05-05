import { IconBox, IconDocument, IconList } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { errorPropertiesLogic, ErrorPropertiesLogicProps } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { mightHaveRecording } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconSubtitles, IconSubtitlesOff } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { Collapsible } from '../Collapsible'
import { ContextDisplay } from '../ContextDisplay'
import { ExceptionAttributesPreview } from '../ExceptionAttributesPreview'
import { ToggleButtonPrimitive } from '../ToggleButton/ToggleButton'
import { exceptionCardLogic } from './exceptionCardLogic'
import { StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './Stacktrace/StacktraceBase'
import { StacktraceGenericDisplay } from './Stacktrace/StacktraceGenericDisplay'
import { StacktraceTextDisplay } from './Stacktrace/StacktraceTextDisplay'

interface ExceptionCardContentProps {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
}

export interface ExceptionCardProps extends ExceptionCardContentProps {
    properties?: ErrorEventProperties
    propertiesLoading: boolean
}

export function ExceptionCard({ issue, issueLoading, properties, propertiesLoading }: ExceptionCardProps): JSX.Element {
    return (
        <BindLogic logic={exceptionCardLogic} props={{ loading: propertiesLoading }}>
            <BindLogic
                logic={errorPropertiesLogic}
                props={{ properties, id: issue?.id ?? 'error' } as ErrorPropertiesLogicProps}
            >
                <ExceptionCardContent issue={issue} issueLoading={issueLoading} />
            </BindLogic>
        </BindLogic>
    )
}

function ExceptionCardContent({ issue, issueLoading }: ExceptionCardContentProps): JSX.Element {
    const { loading, showContext, isExpanded } = useValues(exceptionCardLogic)
    const { properties, exceptionAttributes, additionalProperties, timestamp, sessionId } =
        useValues(errorPropertiesLogic)
    return (
        <LemonCard hoverEffect={false} className="group py-2 px-3 relative overflow-hidden">
            <Collapsible isExpanded={isExpanded} className="pb-1 flex w-full" minHeight="calc(var(--spacing) * 12)">
                <StacktraceIssueDisplay
                    className={cn('flex-grow', showContext && isExpanded ? 'w-2/3' : 'w-full')}
                    truncateMessage={!isExpanded}
                    issue={issue ?? undefined}
                    issueLoading={issueLoading}
                />
                <ContextDisplay
                    className={cn(showContext && isExpanded ? 'w-1/3 pl-2' : 'w-0')}
                    attributes={exceptionAttributes ?? undefined}
                    additionalProperties={additionalProperties}
                    loading={loading}
                />
            </Collapsible>
            <ExceptionCardActions className="absolute top-2 right-3 flex gap-2 items-center z-10">
                <ExceptionCardToggles />
            </ExceptionCardActions>
            <div className="flex justify-between items-center pt-1">
                <ExceptionAttributesPreview attributes={exceptionAttributes} loading={loading} />
                <ExceptionCardActions>
                    {timestamp && <TZLabel className="text-muted text-xs" time={timestamp} />}
                    <ViewRecordingButton
                        sessionId={sessionId}
                        timestamp={timestamp ?? undefined}
                        loading={loading}
                        inModal={true}
                        size="xsmall"
                        type="secondary"
                        disabledReason={mightHaveRecording(properties || {}) ? undefined : 'No recording available'}
                    />
                </ExceptionCardActions>
            </div>
        </LemonCard>
    )
}

function ExceptionCardToggles(): JSX.Element {
    const { showDetails, showAllFrames, showContext, showAsText } = useValues(exceptionCardLogic)
    const { setShowDetails, setShowAllFrames, setShowContext, setShowAsText } = useActions(exceptionCardLogic)
    return (
        <ButtonGroupPrimitive size="sm">
            <ToggleButtonPrimitive className="px-2" checked={showDetails} onCheckedChange={setShowDetails}>
                {showDetails ? (
                    <>
                        <IconSubtitlesOff />
                        Hide details
                    </>
                ) : (
                    <>
                        <IconSubtitles />
                        Show details
                    </>
                )}
            </ToggleButtonPrimitive>
            <ToggleButtonPrimitive iconOnly checked={showAsText} onCheckedChange={setShowAsText} tooltip="Show as text">
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
    )
}

function ExceptionCardActions({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    return (
        <div
            className={cn('flex justify-between items-center gap-1 bg-surface-primary', className)}
            onClick={(e) => e.stopPropagation()}
        >
            {children}
        </div>
    )
}

function StacktraceIssueDisplay({
    issue,
    issueLoading,
    ...stacktraceDisplayProps
}: {
    issue?: ErrorTrackingRelationalIssue
    issueLoading: boolean
} & Omit<StacktraceBaseDisplayProps, 'renderLoading' | 'renderEmpty'>): JSX.Element {
    const { showAsText } = useValues(exceptionCardLogic)
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
