import { LemonButton, LemonButtonWithPopupProps, LemonButtonWithSideAction } from '@posthog/lemon-ui'
import { Select } from 'antd'
import React, { useState } from 'react'
import { IconClose } from '../icons'
import { PopupProps } from '../Popup/Popup'
import './LemonMultiSelect.scss'

export interface LemonMultiSelectOption {
    label: string
    icon?: React.ReactElement
    disabled?: boolean
    'data-attr'?: string
    element?: React.ReactElement
}

export type LemonMultiSelectOptions = Record<string | number, LemonMultiSelectOption>

export interface LemonMultiSelectProps<O extends LemonMultiSelectOptions>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'icon' | 'value' | 'defaultValue' | 'onChange'> {
    options?: O
    value?: (string | number)[] | null
    onChange?: (newValue: (string | number)[] | null) => void
    dropdownMatchSelectWidth?: boolean
    dropdownMaxContentWidth?: boolean
    dropdownPlacement?: PopupProps['placement']
    dropdownMaxWindowDimensions?: boolean
    allowClear?: boolean
}

export function LemonMultiSelect<O extends LemonMultiSelectOptions>({
    value,
    onChange,
    options,
    dropdownPlacement,
    ...buttonProps
}: LemonMultiSelectProps<O>): JSX.Element {
    const [hover, setHover] = useState(false)

    return (
        <div className="LemonMultiSelect" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
            <Select
                mode="tags"
                onChange={(v) => onChange?.(v)}
                tokenSeparators={[',']}
                value={value ? value : []}
                dropdownRender={(menu) => <div className="LemonMultiSelectDropdown">{menu}</div>}
                tagRender={({ label, value, closable, onClose }) => {
                    console.log(label, value)
                    const option = options?.[value as any]

                    return (
                        <LemonButtonWithSideAction
                            size="small"
                            icon={option?.icon}
                            sideAction={{
                                icon: <IconClose />,
                                tooltip: 'Delete',
                                size: 'small',
                                onClick: () => onClose(),
                            }}
                        >
                            {option?.label || value}
                            {option?.element}
                        </LemonButtonWithSideAction>
                    )
                }}
            >
                {Object.entries(options || {}).map(([key, option]) => (
                    <Select.Option key={key} value={key}>
                        <LemonButton
                            icon={option.icon}
                            type={value?.includes(key) ? 'highlighted' : 'stealth'}
                            disabled={option.disabled}
                            fullWidth
                            data-attr={option['data-attr']}
                        >
                            {option.label || key}
                            {option.element}
                        </LemonButton>
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}
