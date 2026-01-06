import './LemonSegmentedButtonWithSelect.scss'

import clsx from 'clsx'
import React, { useMemo } from 'react'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { LemonMenu } from '../LemonMenu/LemonMenu'
import { useSliderPositioning } from '../hooks'
import { LemonSegmentedButtonOption } from './LemonSegmentedButton'

export interface LemonSegmentedButtonWithSelectProps<T extends React.Key> {
    value?: T
    onChange?: (newValue: T, e?: React.MouseEvent) => void
    options: LemonSegmentedButtonOption<T>[]
    /** Number of options to show as buttons (remaining options go in dropdown). If not provided, all options shown as buttons. */
    splitIndex?: number
    size?: LemonButtonProps['size']
    className?: string
    fullWidth?: boolean
}

interface LemonSegmentedButtonWithSelectCSSProperties extends React.CSSProperties {
    '--lemon-segmented-button-slider-width': `${number}px`
    '--lemon-segmented-button-slider-offset': `${number}px`
}

/** Hybrid component showing initial options as segmented buttons and remaining options as a dropdown. */
export function LemonSegmentedButtonWithSelect<T extends React.Key>({
    value,
    onChange,
    options,
    splitIndex,
    size,
    fullWidth,
    className,
}: LemonSegmentedButtonWithSelectProps<T>): JSX.Element {
    const effectiveSplitIndex = splitIndex ?? options.length
    const buttonOptions = options.slice(0, effectiveSplitIndex)
    const dropdownOptions = options.slice(effectiveSplitIndex)
    const shouldShowDropdown = dropdownOptions.length > 0

    // Check if selected value is in dropdown
    const isDropdownValueSelected = dropdownOptions.some((opt) => opt.value === value)

    // Find the selected option for dropdown display
    const selectedDropdownOption = dropdownOptions.find((opt) => opt.value === value)

    const { containerRef, selectionRef, sliderWidth, sliderOffset, transitioning } = useSliderPositioning<
        HTMLDivElement,
        HTMLLIElement
    >(value, 200)

    // Convert dropdown options to menu items
    const menuItems = useMemo(
        () =>
            dropdownOptions.map((option) => ({
                label: option.label ?? '',
                icon: option.icon,
                active: option.value === value,
                onClick: (e: React.MouseEvent) => {
                    onChange?.(option.value, e)
                },
                disabledReason: option.disabledReason,
                tooltip: option.tooltip,
                'data-attr': option['data-attr'],
            })),
        [dropdownOptions, value, onChange]
    )

    const isFirstSelected = value === buttonOptions[0]?.value
    const isLastButtonSelected = value === buttonOptions[buttonOptions.length - 1]?.value && !isDropdownValueSelected

    return (
        <div
            className={clsx(
                'LemonSegmentedButtonWithSelect',
                fullWidth && 'LemonSegmentedButtonWithSelect--full-width',
                transitioning && 'LemonSegmentedButtonWithSelect--transitioning',
                className
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-segmented-button-slider-width': `${sliderWidth}px`,
                    '--lemon-segmented-button-slider-offset': `${sliderOffset}px`,
                } as LemonSegmentedButtonWithSelectCSSProperties
            }
            ref={containerRef}
        >
            {sliderWidth > 0 && (
                <div
                    className={clsx(
                        'LemonSegmentedButtonWithSelect__slider',
                        isFirstSelected
                            ? 'LemonSegmentedButtonWithSelect__slider--first'
                            : isLastButtonSelected || isDropdownValueSelected
                              ? 'LemonSegmentedButtonWithSelect__slider--last'
                              : null
                    )}
                />
            )}
            <ul>
                {buttonOptions.map((option) => (
                    <li
                        key={option.value}
                        className={clsx(
                            'LemonSegmentedButtonWithSelect__option',
                            option.disabledReason && 'LemonSegmentedButtonWithSelect__option--disabled',
                            option.value === value && 'LemonSegmentedButtonWithSelect__option--selected'
                        )}
                        ref={option.value === value ? selectionRef : undefined}
                    >
                        <LemonButton
                            type={option.value === value ? 'primary' : 'secondary'}
                            size={size}
                            fullWidth
                            disabledReason={option.disabledReason}
                            onClick={(e) => {
                                if (!option.disabledReason) {
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
                ))}
                {shouldShowDropdown && (
                    <li
                        className={clsx(
                            'LemonSegmentedButtonWithSelect__option',
                            'LemonSegmentedButtonWithSelect__option--dropdown',
                            isDropdownValueSelected && 'LemonSegmentedButtonWithSelect__option--selected'
                        )}
                        ref={isDropdownValueSelected ? selectionRef : undefined}
                    >
                        <LemonMenu items={menuItems}>
                            <LemonButton
                                type={isDropdownValueSelected ? 'primary' : 'secondary'}
                                size={size}
                                fullWidth
                                icon={selectedDropdownOption?.icon}
                                center
                            >
                                {selectedDropdownOption?.label ?? dropdownOptions[0]?.label}
                            </LemonButton>
                        </LemonMenu>
                    </li>
                )}
            </ul>
        </div>
    )
}
