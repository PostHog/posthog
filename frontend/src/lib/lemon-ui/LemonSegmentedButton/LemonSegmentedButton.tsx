import clsx from 'clsx'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import React, { useLayoutEffect, useCallback, useRef, useState } from 'react'
import { LemonButton } from '../LemonButton'
import './LemonSegmentedButton.scss'

export interface LemonSegmentedButtonOption<T extends React.Key> {
    value: T
    label: string | JSX.Element
    icon?: React.ReactElement
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string
    tooltip?: string | JSX.Element
    'data-attr'?: string
}

export interface LemonSegmentedButtonProps<T extends React.Key> {
    value?: T
    onChange?: (newValue: T) => void
    options: LemonSegmentedButtonOption<T>[]
}

interface LemonSegmentedButtonCSSProperties extends React.CSSProperties {
    '--lemon-segmented-button-selection-width': `${number}px`
    '--lemon-segmented-button-selection-offset': `${number}px`
}

/** Button-radio hybrid. Single choice. */
export function LemonSegmentedButton<T extends React.Key>({
    value,
    onChange,
    options,
}: LemonSegmentedButtonProps<T>): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const selectedOptionRef = useRef<HTMLButtonElement>(null)
    const [selectionWidth, setSelectionWidth] = useState(0)
    const [selectionOffset, setSelectionOffset] = useState(0)

    const recalculateSelectionBounds = useCallback(() => {
        if (containerRef.current && selectedOptionRef.current) {
            const { left: containerLeft } = containerRef.current.getBoundingClientRect()
            const { width, left: selectedOptionleft } = selectedOptionRef.current.getBoundingClientRect()
            setSelectionWidth(width)
            setSelectionOffset(selectedOptionleft - containerLeft - 1) // -1px to account for border
        }
    }, [])
    useLayoutEffect(() => recalculateSelectionBounds(), [value])
    useResizeObserver({ ref: containerRef, onResize: () => recalculateSelectionBounds() })

    return (
        <div
            className="LemonSegmentedButton"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-segmented-button-selection-width': `${selectionWidth}px`,
                    '--lemon-segmented-button-selection-offset': `${selectionOffset}px`,
                } as LemonSegmentedButtonCSSProperties
            }
            ref={containerRef}
        >
            {selectionWidth > 0 && (
                <div
                    className={clsx(
                        'LemonSegmentedButton__slider',
                        value === options[0].value
                            ? 'LemonSegmentedButton__slider--first'
                            : value === options[options.length - 1].value
                            ? 'LemonSegmentedButton__slider--last'
                            : null
                    )}
                />
            )}
            <ul>
                {options.map((option) => (
                    <li
                        key={option.value}
                        className={clsx(
                            'LemonSegmentedButton__option',
                            option.disabledReason && 'LemonSegmentedButton__option--disabled',
                            option.value === value && 'LemonSegmentedButton__option--selected'
                        )}
                    >
                        <LemonButton /* The ref is on the button and not on the list item so that the border isn't counted */
                            ref={option.value === value ? selectedOptionRef : undefined}
                            disabledReason={option.disabledReason}
                            onClick={() => {
                                if (!option.disabledReason) {
                                    onChange?.(option.value)
                                }
                            }}
                            icon={option.icon}
                            data-attr={option['data-attr']}
                        >
                            {option.label}
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </div>
    )
}
