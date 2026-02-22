import './CardMeta.scss'

import clsx from 'clsx'
import React from 'react'
import { Transition } from 'react-transition-group'

import { IconPieChart } from '@posthog/icons'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { useDelayedHover } from 'lib/hooks/useDelayedHover'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconSubtitles, IconSubtitlesOff } from 'lib/lemon-ui/icons'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

import { InsightColor } from '~/types'

export interface Resizeable {
    showResizeHandles?: boolean
    canResizeWidth?: boolean
}

export interface CardMetaProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'className'> {
    compact?: boolean
    areDetailsShown?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
    ribbonColor?: InsightColor | null
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
    /** Whether the  controls for showing details should be enabled or not. */
    showDetailsControls?: boolean
    content?: JSX.Element | null
    metaDetails?: JSX.Element | null
    /** Buttons to show in the editing controls dropdown. */
    moreButtons?: JSX.Element
    /** Tooltip for the editing controls dropdown. */
    moreTooltip?: string
    /** Tooltip for the details button. */
    detailsTooltip?: string
    topHeading?: JSX.Element | null
    samplingFactor?: number | null
    /** Additional controls to show in the top controls area */
    extraControls?: JSX.Element | null
    /** Description shown in the compact popover. */
    metaDescription?: JSX.Element | null
    /** Insight title shown in the compact popover. */
    metaTitle?: string
    /** Raw description text for editing. */
    metaDescriptionText?: string
    /** When provided, makes title/description editable in the compact popover. */
    onMetaSave?: (updates: { name?: string; description?: string }) => void
}

export function CardMeta({
    compact,
    ribbonColor,
    showEditingControls,
    showDetailsControls,
    content: meta,
    metaDetails,
    moreButtons,
    moreTooltip,
    topHeading,
    areDetailsShown,
    setAreDetailsShown,
    detailsTooltip,
    className,
    samplingFactor,
    extraControls,
    metaDescription,
    metaTitle,
    metaDescriptionText,
    onMetaSave,
}: CardMetaProps): JSX.Element {
    const { ref: primaryRef, width: primaryWidth } = useResizeObserver()
    const { ref: detailsRef, height: detailsHeight } = useResizeObserver()
    const { ref: topRef, width: topWidth } = useResizeObserver()
    const { ref: headingRef, width: headingWidth } = useResizeObserver()

    // Calculate available space for controls (doesn't depend on label state, so no cyclic dependency)
    const controlsAvailableSpace = (topWidth ?? 0) - (headingWidth ?? 0)

    // Estimate space needed for controls with labels
    // These are approximate widths based on current button styles
    const buttonsWithLabels = (!compact && showDetailsControls ? 1 : 0) + (extraControls ? 1 : 0)
    const neededWidth = buttonsWithLabels * 140 // 140px per button

    // Show labels if card is wide enough AND there's room for labeled buttons
    // But also when in storybook to make it neater
    const showControlsLabels =
        inStorybook() ||
        inStorybookTestRunner() ||
        (!!primaryWidth && primaryWidth > 480 && controlsAvailableSpace >= neededWidth)

    const {
        visible: detailsPopoverVisible,
        show: showDetails,
        hide: hideDetails,
    } = useDelayedHover({ showDelay: 500, hideDelay: 200 })

    return (
        <div
            className={clsx(
                'CardMeta',
                className,
                compact && 'CardMeta--compact',
                areDetailsShown && 'CardMeta--details-shown'
            )}
        >
            <div className="CardMeta__primary" ref={compact ? undefined : primaryRef}>
                {ribbonColor &&
                    ribbonColor !==
                        InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('CardMeta__ribbon', ribbonColor)} />
                    )}
                <div className="CardMeta__main">
                    {compact ? (
                        <>
                            <div className="CardMeta__top">
                                <h5 className="CardMeta__heading">{topHeading}</h5>
                                <div className="CardMeta__controls">
                                    {showEditingControls &&
                                        (moreTooltip ? (
                                            <Tooltip title={moreTooltip}>
                                                <More overlay={moreButtons} />
                                            </Tooltip>
                                        ) : (
                                            <More overlay={moreButtons} />
                                        ))}
                                </div>
                            </div>
                            <Popover
                                visible={detailsPopoverVisible}
                                placement="bottom-start"
                                showArrow
                                onMouseEnterInside={showDetails}
                                onMouseLeaveInside={hideDetails}
                                overlay={
                                    <div className="p-4 max-w-md space-y-2" onMouseDown={(e) => e.stopPropagation()}>
                                        <h4 className="font-semibold m-0 mb-1">{topHeading}</h4>
                                        {onMetaSave ? (
                                            <>
                                                <EditableField
                                                    name="title"
                                                    value={metaTitle || ''}
                                                    onSave={(value) => onMetaSave({ name: value })}
                                                    placeholder="Untitled"
                                                    saveOnBlur
                                                    clickToEdit
                                                    compactButtons
                                                    compactIcon
                                                    className="font-semibold text-sm"
                                                    data-attr="insight-card-title"
                                                />
                                                <EditableField
                                                    name="description"
                                                    value={metaDescriptionText || ''}
                                                    onSave={(value) => onMetaSave({ description: value })}
                                                    placeholder="Enter description (optional)"
                                                    saveOnBlur
                                                    clickToEdit
                                                    multiline
                                                    markdown
                                                    compactButtons
                                                    compactIcon
                                                    className="text-xs w-full"
                                                    data-attr="insight-card-description"
                                                />
                                            </>
                                        ) : (
                                            <>
                                                {metaTitle && <p className="font-semibold m-0">{metaTitle}</p>}
                                                {metaDescription}
                                            </>
                                        )}
                                        {metaDetails}
                                    </div>
                                }
                            >
                                <div
                                    className="overflow-hidden min-w-0"
                                    onMouseEnter={showDetails}
                                    onMouseLeave={hideDetails}
                                >
                                    {meta}
                                </div>
                            </Popover>
                        </>
                    ) : (
                        <>
                            <div className="CardMeta__top" ref={topRef}>
                                <h5 ref={headingRef}>
                                    {topHeading}
                                    {samplingFactor && samplingFactor < 1 && (
                                        <Tooltip
                                            title={`Results calculated from ${100 * samplingFactor}% of users`}
                                            placement="right"
                                        >
                                            <IconPieChart
                                                className="ml-1.5 text-base align-[-0.25em]"
                                                style={{ color: 'var(--primary-3000-hover)' }}
                                            />
                                        </Tooltip>
                                    )}
                                </h5>
                                <div className="CardMeta__controls">
                                    {extraControls &&
                                        React.cloneElement(extraControls, {
                                            ...extraControls.props,
                                            showLabel: showControlsLabels,
                                        })}
                                    {showDetailsControls && setAreDetailsShown && (
                                        <Tooltip title={detailsTooltip}>
                                            <LemonButton
                                                icon={!areDetailsShown ? <IconSubtitles /> : <IconSubtitlesOff />}
                                                onClick={() => setAreDetailsShown((state) => !state)}
                                                size="small"
                                                active={areDetailsShown}
                                            >
                                                {showControlsLabels && `${!areDetailsShown ? 'Show' : 'Hide'} details`}
                                            </LemonButton>
                                        </Tooltip>
                                    )}
                                    {showEditingControls &&
                                        (moreTooltip ? (
                                            <Tooltip title={moreTooltip}>
                                                <More overlay={moreButtons} />
                                            </Tooltip>
                                        ) : (
                                            <More overlay={moreButtons} />
                                        ))}
                                </div>
                            </div>
                            {meta}
                        </>
                    )}
                </div>
            </div>

            <div className="CardMeta__divider" />
            {!compact && (
                <div
                    className="CardMeta__details"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        height: areDetailsShown && detailsHeight ? detailsHeight + 1 : 0,
                    }}
                >
                    {/* By using a transition about displaying then we make sure we aren't rendering the content when not needed */}
                    <Transition in={areDetailsShown} timeout={200} mountOnEnter unmountOnExit>
                        <div className="CardMeta__details__content" ref={detailsRef}>
                            {/* Stops the padding getting in the height calc  */}
                            <div className="p-4">{metaDetails}</div>
                        </div>
                    </Transition>
                </div>
            )}
        </div>
    )
}
