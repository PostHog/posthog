import { IconChevronDown, IconEye, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonDropdown, LemonSwitch, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FingerprintComponents } from 'lib/components/Errors/ErrorDisplay'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { Collapsible } from './Collapsible'
import { StacktraceDisplay } from './StacktraceDisplay'
import { TimeBoundary } from './TimeBoundary'

export function IssueCard(): JSX.Element {
    const {
        propertiesLoading,
        firstSeen,
        issueLoading,
        summaryLoading,
        lastSeen,
        showFingerprint,
        fingerprintRecords,
        stacktraceExpanded,
    } = useValues(errorTrackingIssueSceneLogic)
    const { setStacktraceExpanded } = useActions(errorTrackingIssueSceneLogic)
    return (
        <LemonCard
            hoverEffect={false}
            className="p-0 group cursor-pointer p-2 px-3 relative"
            onClick={() => setStacktraceExpanded(!stacktraceExpanded)}
        >
            <Collapsible isExpanded={stacktraceExpanded} className="pb-2" minHeight="calc(var(--spacing) * 13)">
                <StacktraceDisplay />
            </Collapsible>
            <div className="absolute top-2 right-3">
                <ShowDropdownMenu />
            </div>
            <div className="flex justify-between items-center">
                <StacktraceExpander />
                <div className="flex justify-between items-center gap-1 ">
                    <TimeBoundary
                        time={firstSeen}
                        label="First Seen"
                        loading={issueLoading}
                        updateDateRange={(dateRange) => {
                            return {
                                ...dateRange,
                                date_from: firstSeen?.startOf('minute').toISOString(),
                            }
                        }}
                    />
                    <IconChevronRight />
                    <TimeBoundary
                        time={lastSeen}
                        label="Last Seen"
                        loading={summaryLoading}
                        updateDateRange={(dateRange) => {
                            return {
                                ...dateRange,
                                date_to: lastSeen?.endOf('minute').toISOString(),
                            }
                        }}
                    />
                    {!propertiesLoading && showFingerprint && fingerprintRecords && (
                        <>
                            <LemonDivider vertical={true} className="h-3 self-center mx-1" />
                            <FingerprintComponents components={fingerprintRecords} />
                        </>
                    )}
                </div>
            </div>
        </LemonCard>
    )
}

function ShowDropdownMenu(): JSX.Element {
    return (
        <LemonDropdown overlay={<ShowPopoverContent />} placement="bottom-end" closeOnClickInside={false}>
            <LemonButton
                size="xsmall"
                onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                }}
                sideIcon={null}
            >
                <IconEye />
            </LemonButton>
        </LemonDropdown>
    )
}

function ShowPopoverContent(): JSX.Element {
    const { showAllFrames, hasNonInAppFrames, frameOrderReversed, fingerprintRecords, showFingerprint } =
        useValues(errorTrackingIssueSceneLogic)
    const { setShowAllFrames, setFrameOrderReversed, setShowFingerprint } = useActions(errorTrackingIssueSceneLogic)
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
            {renderSwitch('Fingerprint', showFingerprint, setShowFingerprint, fingerprintRecords == null)}
            {renderSwitch('Reverse order', frameOrderReversed, setFrameOrderReversed)}
        </div>
    )
}

function StacktraceExpander(): JSX.Element {
    const { stacktraceExpanded, propertiesLoading, hasStacktrace } = useValues(errorTrackingIssueSceneLogic)
    return (
        <span className="flex items-center gap-1 text-muted group-hover:text-brand-red">
            {match([propertiesLoading, hasStacktrace])
                .with([true, P.any], () => (
                    <span>
                        <Spinner />
                    </span>
                ))
                .with([false, false], () => (
                    <>
                        <IconWarning />
                        No stacktrace available
                    </>
                ))
                .with([false, true], () => {
                    return (
                        <>
                            <span className="text-xs">
                                {stacktraceExpanded ? 'Hide stacktrace' : 'Show stacktrace'}
                            </span>
                            <IconChevronDown
                                className={cn('transition-transform duration-300', {
                                    'rotate-180': stacktraceExpanded,
                                })}
                            />
                        </>
                    )
                })
                .exhaustive()}
        </span>
    )
}
