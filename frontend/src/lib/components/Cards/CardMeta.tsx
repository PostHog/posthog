import './CardMeta.scss'

import clsx from 'clsx'
import React from 'react'
import { Transition } from 'react-transition-group'

import { IconPieChart } from '@posthog/icons'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconSubtitles, IconSubtitlesOff } from 'lib/lemon-ui/icons'

import { InsightColor } from '~/types'

export interface Resizeable {
    showResizeHandles?: boolean
    canResizeWidth?: boolean
}

export interface CardMetaProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'className'> {
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
}

export function CardMeta({
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
}: CardMetaProps): JSX.Element {
    const { ref: primaryRef, width: primaryWidth } = useResizeObserver()
    const { ref: detailsRef, height: detailsHeight } = useResizeObserver()

    const showDetailsButtonLabel = !!primaryWidth && primaryWidth > 480

    return (
        <div className={clsx('CardMeta', className, areDetailsShown && 'CardMeta--details-shown')}>
            <div className="CardMeta__primary" ref={primaryRef}>
                {ribbonColor &&
                    ribbonColor !==
                        InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('CardMeta__ribbon', ribbonColor)} />
                    )}
                <div className="CardMeta__main">
                    <div className="CardMeta__top">
                        <h5>
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
                            {extraControls}
                            {showDetailsControls && setAreDetailsShown && (
                                <Tooltip title={detailsTooltip}>
                                    <LemonButton
                                        icon={!areDetailsShown ? <IconSubtitles /> : <IconSubtitlesOff />}
                                        onClick={() => setAreDetailsShown((state) => !state)}
                                        size="small"
                                        active={areDetailsShown}
                                    >
                                        {showDetailsButtonLabel && `${!areDetailsShown ? 'Show' : 'Hide'} details`}
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
                </div>
            </div>

            <div className="CardMeta__divider" />
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
        </div>
    )
}
