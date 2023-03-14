import React, { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { humanFriendlyDuration } from 'lib/utils'
import { useThrottledCallback } from 'use-debounce'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { Noun } from '~/models/groupsModel'
import { ValueInspectorButton } from '../ValueInspectorButton'

interface AverageTimeInspectorProps {
    onClick: (e?: React.MouseEvent) => void
    disabled?: boolean
    averageTime: number
    aggregationTargetLabel: Noun
}
export function AverageTimeInspector({
    onClick,
    disabled,
    averageTime,
    aggregationTargetLabel,
}: AverageTimeInspectorProps): JSX.Element {
    // Inspector button which automatically shows/hides the info text.
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const infoTextRef = useRef<HTMLDivElement | null>(null)
    const buttonRef = useRef<HTMLDivElement | null>(null)
    const [infoTextVisible, setInfoTextVisible] = useState(true)

    function decideTextVisible(): void {
        // Show/hide label position based on whether both items fit horizontally
        const wrapperWidth = wrapperRef.current?.clientWidth ?? null
        const infoTextWidth = infoTextRef.current?.offsetWidth ?? null
        const buttonWidth = buttonRef.current?.offsetWidth ?? null

        if (wrapperWidth !== null && infoTextWidth !== null && buttonWidth !== null) {
            if (infoTextWidth + buttonWidth <= wrapperWidth) {
                setInfoTextVisible(true)
                return
            }
        }
        setInfoTextVisible(false)
    }

    useEffect(() => {
        decideTextVisible()
    }, [])

    useResizeObserver({
        onResize: useThrottledCallback(decideTextVisible, 200),
        ref: wrapperRef,
    })

    return (
        <div ref={wrapperRef}>
            <span ref={infoTextRef} className={clsx('inline-block text-muted-alt', !infoTextVisible && 'invisible')}>
                Average time:{' '}
            </span>
            <ValueInspectorButton
                innerRef={buttonRef}
                style={{ paddingLeft: 0, paddingRight: 0 }}
                onClick={onClick}
                disabled={disabled}
                title={`Average of time elapsed for each ${aggregationTargetLabel.singular} between completing this step and starting the next one.`}
            >
                {humanFriendlyDuration(averageTime, 2)}
            </ValueInspectorButton>
        </div>
    )
}
