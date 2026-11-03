import React, { useCallback, useEffect, useRef, useState } from 'react'

import { IconInfo } from '@posthog/icons'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'

export function CompactInfoPopover({
    onVisibilityChange,
    popoverTopHeading,
    metaTitle,
    metaDescription,
    metaDescriptionText,
    onMetaSave,
    metaDetails,
}: {
    onVisibilityChange?: (visible: boolean) => void
    popoverTopHeading?: JSX.Element | null
    metaTitle: string
    metaDescription?: JSX.Element | null
    metaDescriptionText: string
    onMetaSave?: (updates: { name?: string; description?: string }) => void
    metaDetails?: JSX.Element | null
}): JSX.Element {
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
                <div
                    className="p-4 max-w-md space-y-3"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                    }}
                >
                    {popoverTopHeading && (
                        <h5 className="uppercase text-xs font-bold text-muted tracking-wide m-0">
                            {popoverTopHeading}
                        </h5>
                    )}
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
                                className="font-semibold text-sm mt-1"
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
