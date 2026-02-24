import './LemonSegmentedButton.scss'

import clsx from 'clsx'
import React from 'react'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { useSliderPositioning } from '../hooks'

// Expects at least one of label or icon to be provided
export type LemonSegmentedButtonOption<T extends React.Key> = { value: T } & (
    | { label: string | JSX.Element }
    | { icon: JSX.Element }
) & {
        label?: string | JSX.Element
        icon?: JSX.Element
        disabledReason?: string
        tooltip?: string | JSX.Element
        'data-attr'?: string
    }

export interface LemonSegmentedButtonProps<T extends React.Key> {
    value?: T
    onChange?: (newValue: T, e: React.MouseEvent) => void
    options: LemonSegmentedButtonOption<T>[]
    disabledReason?: string
    size?: LemonButtonProps['size']
    className?: string
    fullWidth?: boolean
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
    disabledReason,
    size,
    fullWidth,
    className,
}: LemonSegmentedButtonProps<T>): JSX.Element {
    const { containerRef, selectionRef, sliderWidth, sliderOffset, transitioning } = useSliderPositioning<
        HTMLDivElement,
        HTMLLIElement
    >(value, 200)

    return (
        <div
            className={clsx(
                'LemonSegmentedButton',
                fullWidth && 'LemonSegmentedButton--full-width',
                transitioning && 'LemonSegmentedButton--transitioning',
                className
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-segmented-button-slider-width': `${sliderWidth}px`,
                    '--lemon-segmented-button-slider-offset': `${sliderOffset}px`,
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
                {options.map((option) => {
                    const optionDisabledReason = option.disabledReason ?? disabledReason

                    return (
                        <li
                            key={option.value}
                            className={clsx(
                                'LemonSegmentedButton__option',
                                optionDisabledReason && 'LemonSegmentedButton__option--disabled',
                                option.value === value && 'LemonSegmentedButton__option--selected'
                            )}
                            ref={option.value === value ? selectionRef : undefined}
                        >
                            <LemonButton
                                type={option.value === value ? 'primary' : 'secondary'}
                                size={size}
                                fullWidth
                                disabledReason={optionDisabledReason}
                                onClick={(e) => {
                                    if (!optionDisabledReason) {
                                        onChange?.(option.value, e)
                                    }
                                }}
                                icon={option.icon}
                                data-attr={option['data-attr']}
                                tooltip={option.tooltip}
                                center
                            >
                                {option.label}
                            </LemonButton>
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
