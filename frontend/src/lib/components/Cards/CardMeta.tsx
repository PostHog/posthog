import './CardMeta.scss'

import clsx from 'clsx'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { IconRefresh, IconSubtitles, IconSubtitlesOff } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Transition } from 'react-transition-group'

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
    refresh?: () => void
    refreshDisabledReason?: string
    meta?: JSX.Element | null
    metaDetails?: JSX.Element | null
    moreButtons?: JSX.Element | null
    topHeading?: JSX.Element | null
    samplingNotice?: JSX.Element | null
}

export function CardMeta({
    ribbonColor,
    showEditingControls,
    showDetailsControls,
    refresh,
    refreshDisabledReason,
    meta,
    metaDetails,
    moreButtons,
    topHeading,
    areDetailsShown,
    setAreDetailsShown,
    className,
    samplingNotice,
}: CardMetaProps): JSX.Element {
    const { ref: primaryRef, width: primaryWidth } = useResizeObserver()
    const { ref: detailsRef, height: detailsHeight } = useResizeObserver()

    const showDetailsButtonLabel = !!primaryWidth && primaryWidth > 480

    return (
        <div
            className={clsx(
                'CardMeta',
                className,
                showDetailsControls && 'CardMeta--with-details',
                areDetailsShown && 'CardMeta--details-shown'
            )}
        >
            <div className="CardMeta__primary" ref={primaryRef}>
                {ribbonColor &&
                    ribbonColor !==
                        InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('CardMeta__ribbon', ribbonColor)} />
                    )}
                <div className="CardMeta__main">
                    <div className="CardMeta__top">
                        <h5>{topHeading}</h5>
                        <div className="CardMeta__controls">
                            {showDetailsControls && setAreDetailsShown && (
                                <LemonButton
                                    icon={!areDetailsShown ? <IconSubtitles /> : <IconSubtitlesOff />}
                                    onClick={() => setAreDetailsShown((state) => !state)}
                                    size="small"
                                    active={areDetailsShown}
                                >
                                    {showDetailsButtonLabel && `${!areDetailsShown ? 'Show' : 'Hide'} details`}
                                </LemonButton>
                            )}
                            {showEditingControls && refresh && (
                                <LemonButton
                                    icon={<IconRefresh />}
                                    size="small"
                                    onClick={() => refresh()}
                                    disabledReason={refreshDisabledReason}
                                />
                            )}
                            {samplingNotice ? samplingNotice : null}
                            {showEditingControls && <More overlay={moreButtons} />}
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
