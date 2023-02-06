import clsx from 'clsx'
import React from 'react'
import { LemonButton } from '../LemonButton'
import { useSliderPositioning } from '../hooks'
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
    size?: 'small' | 'medium'
}

interface LemonSegmentedButtonCSSProperties extends React.CSSProperties {
    '--lemon-segmented-button-slider-width': `${number}px`
    '--lemon-segmented-button-slider-offset': `${number}px`
}

/** Button-radio hybrid. Single choice. */
export function LemonSegmentedButton<T extends React.Key>({
    value,
    onChange,
    options,
    size,
}: LemonSegmentedButtonProps<T>): JSX.Element {
    const { containerRef, selectionRef, sliderWidth, sliderOffset } = useSliderPositioning<
        HTMLDivElement,
        HTMLButtonElement
    >(value)

    return (
        <div
            className="LemonSegmentedButton"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-segmented-button-slider-width': `${sliderWidth}px`,
                    // Subtract 1px from offset to account for border-right
                    '--lemon-segmented-button-slider-offset': `${sliderOffset - 1}px`,
                } as LemonSegmentedButtonCSSProperties
            }
            ref={containerRef}
        >
            {sliderWidth > 0 && (
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
                            ref={option.value === value ? selectionRef : undefined}
                            size={size}
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
