import clsx from 'clsx'
import React from 'react'
import { LemonButton, LemonButtonProps } from '../LemonButton'
import { useSliderPositioning } from '../hooks'
import './LemonSegmentedButton.scss'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

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
    size,
    fullWidth,
    className,
}: LemonSegmentedButtonProps<T>): JSX.Element {
    const { containerRef, selectionRef, sliderWidth, sliderOffset, transitioning } = useSliderPositioning<
        HTMLDivElement,
        HTMLLIElement
    >(value, 200)
    const { featureFlags } = useValues(featureFlagLogic)

    const has3000 = featureFlags[FEATURE_FLAGS.POSTHOG_3000]

    let buttonProps = {}

    if (has3000) {
        buttonProps = { status: 'stealth', type: 'secondary', motion: false }
    }

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
                {options.map((option) => (
                    <li
                        key={option.value}
                        className={clsx(
                            'LemonSegmentedButton__option',
                            option.disabledReason && 'LemonSegmentedButton__option--disabled',
                            option.value === value && 'LemonSegmentedButton__option--selected'
                        )}
                        ref={option.value === value ? selectionRef : undefined}
                    >
                        <LemonButton
                            size={size}
                            fullWidth
                            disabledReason={option.disabledReason}
                            onClick={() => {
                                if (!option.disabledReason) {
                                    onChange?.(option.value)
                                }
                            }}
                            icon={option.icon}
                            data-attr={option['data-attr']}
                            center
                            {...buttonProps}
                        >
                            {option.label}
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </div>
    )
}
