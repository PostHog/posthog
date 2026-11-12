import React, { useCallback, useEffect, useRef, useState } from 'react'

import { IconInfo } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'

import { CompactInfoPopoverContent, type CompactInfoPopoverContentProps } from './CompactInfoPopoverContent'

export function CompactInfoPopover({
    onVisibilityChange,
    popoverTopHeading,
    metaTitle,
    metaDescription,
    metaDescriptionText,
    onMetaSave,
    metaDetails,
}: CompactInfoPopoverContentProps & { onVisibilityChange?: (visible: boolean) => void }): JSX.Element {
    const [popoverVisible, setPopoverVisible] = useState(false)
    useEffect(() => {
        onVisibilityChange?.(popoverVisible)
    }, [popoverVisible, onVisibilityChange])
    useEffect(() => () => onVisibilityChange?.(false), [onVisibilityChange])
    const [pinned, setPinned] = useState(false)
    const hoverTimerRef = useRef<ReturnType<typeof setTimeout>>()

    useEffect(() => () => clearTimeout(hoverTimerRef.current), [])

    const clearHoverTimer = (): void => clearTimeout(hoverTimerRef.current)

    const showDetails = useCallback(() => {
        clearHoverTimer()
        hoverTimerRef.current = setTimeout(() => setPopoverVisible(true), 300)
    }, [])

    const hideDetails = useCallback(() => {
        clearHoverTimer()
        hoverTimerRef.current = setTimeout(() => setPopoverVisible(false), 800)
    }, [])

    const handleClickInfo = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            e.stopPropagation()
            clearHoverTimer()
            const newPinned = !pinned
            setPinned(newPinned)
            setPopoverVisible(newPinned)
        },
        [pinned]
    )

    const handleClickOutside = useCallback(() => {
        clearHoverTimer()
        setPinned(false)
        setPopoverVisible(false)
    }, [])

    return (
        <Popover
            visible={popoverVisible}
            placement="bottom"
            showArrow
            onClickOutside={handleClickOutside}
            onMouseEnterInside={showDetails}
            onMouseLeaveInside={pinned ? undefined : hideDetails}
            overlay={
                <CompactInfoPopoverContent
                    popoverTopHeading={popoverTopHeading}
                    metaTitle={metaTitle}
                    metaDescription={metaDescription}
                    metaDescriptionText={metaDescriptionText}
                    onMetaSave={onMetaSave}
                    metaDetails={metaDetails}
                />
            }
        >
            <span
                className="ml-1 flex-shrink-0"
                onMouseEnter={showDetails}
                onMouseLeave={pinned ? undefined : hideDetails}
            >
                <LemonButton
                    icon={<IconInfo />}
                    size="small"
                    noPadding
                    data-attr="card-meta-info"
                    onClick={handleClickInfo}
                />
            </span>
        </Popover>
    )
}
