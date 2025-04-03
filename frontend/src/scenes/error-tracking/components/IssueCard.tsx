import { IconChevronDown, IconEye, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonDropdown, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FingerprintComponents } from 'lib/components/Errors/ErrorDisplay'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { cn } from 'lib/utils/css-classes'
import { Children, Fragment, useState } from 'react'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { cancelEvent } from '../utils'
import { Collapsible } from './Collapsible'
import { ContextDisplay } from './ContextDisplay'
import { IssueDateRange } from './IssueDateRange'
import { StacktraceDisplay } from './StacktraceDisplay'

export function IssueCard(): JSX.Element {
    const { propertiesLoading, properties, sessionId, showFingerprint, fingerprintRecords, showStacktrace } =
        useValues(errorTrackingIssueSceneLogic)
    const { setShowStacktrace } = useActions(errorTrackingIssueSceneLogic)
    const [showMenuVisible, setShowMenuVisible] = useState(false)
    return (
        <LemonCard
            hoverEffect={false}
            className="p-0 group cursor-pointer p-2 px-3 relative"
            onClick={() => {
                if (!showMenuVisible) {
                    setShowStacktrace(!showStacktrace)
                }
            }}
        >
            <Collapsible isExpanded={showStacktrace} className="pb-2 flex" minHeight="calc(var(--spacing) * 13)">
                <StacktraceDisplay className="flex-grow" />
                <ContextDisplay />
            </Collapsible>
            <div className="absolute top-2 right-3">
                <ShowDropdownMenu visible={showMenuVisible} setVisible={setShowMenuVisible} />
            </div>
            <div className="flex justify-between items-center">
                <StacktraceExpander />
                <IssueCardActions>
                    {!propertiesLoading && showFingerprint && fingerprintRecords && (
                        <FingerprintComponents components={fingerprintRecords} />
                    )}
                    <IssueDateRange />
                    <ViewRecordingButton
                        sessionId={sessionId}
                        timestamp={properties.timestamp}
                        loading={propertiesLoading}
                        inModal={true}
                        size="xsmall"
                        type="secondary"
                        disabledReason={sessionId ? undefined : 'No recording available'}
                    />
                </IssueCardActions>
            </div>
        </LemonCard>
    )
}

function ShowDropdownMenu({
    visible,
    setVisible,
}: {
    visible: boolean
    setVisible: (value: boolean) => void
}): JSX.Element {
    return (
        <LemonDropdown
            overlay={<ShowPopoverContent />}
            placement="bottom-end"
            closeOnClickInside={false}
            visible={visible}
            onClickOutside={() => setVisible(false)}
        >
            <LemonButton
                size="xsmall"
                onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    setVisible(!visible)
                }}
                sideIcon={null}
            >
                <IconEye />
            </LemonButton>
        </LemonDropdown>
    )
}

function ShowPopoverContent(): JSX.Element {
    const { showAllFrames, showContext, hasNonInAppFrames, frameOrderReversed, fingerprintRecords, showFingerprint } =
        useValues(errorTrackingIssueSceneLogic)
    const { setShowAllFrames, setShowContext, setFrameOrderReversed, setShowFingerprint } =
        useActions(errorTrackingIssueSceneLogic)
    function renderSwitch(
        label: string,
        value: boolean,
        setter: (value: boolean) => void,
        disabled: boolean = false
    ): JSX.Element {
        return (
            <LemonSwitch
                label={label}
                checked={value}
                size="small"
                fullWidth={true}
                onChange={setter}
                disabled={disabled}
            />
        )
    }
    return (
        <div className="p-1 flex flex-col gap-2">
            {renderSwitch('All frames', showAllFrames, setShowAllFrames, !hasNonInAppFrames)}
            {renderSwitch('Context', showContext, setShowContext, false)}
            {renderSwitch('Fingerprint', showFingerprint, setShowFingerprint, fingerprintRecords == null)}
            {renderSwitch('Reverse order', frameOrderReversed, setFrameOrderReversed)}
        </div>
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
                        <span className="text-xs">{showStacktrace ? 'Hide stacktrace' : 'Show stacktrace'}</span>
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
                .map((child, index, array) => (
                    <Fragment key={index}>
                        {child}
                        {index !== array.length - 1 && (
                            <LemonDivider vertical={true} className="h-3 mx-1 self-center" />
                        )}
                    </Fragment>
                ))}
        </div>
    )
}
