import { Select } from 'antd'
import React, { useState } from 'react'
import { LemonSnack } from '../LemonSnack/LemonSnack'
import './LemonMultiSelect.scss'

export interface LemonMultiSelectOption {
    label: string | React.ReactElement
    disabled?: boolean
    'data-attr'?: string
}

export type LemonMultiSelectOptions = Record<string | number, LemonMultiSelectOption>

export interface LemonMultiSelectProps<O extends LemonMultiSelectOptions> {
    options?: O
    value?: (string | number)[] | null
    disabled?: boolean
    placeholder?: string
    onChange?: (newValue: (string | number)[] | null) => void
}

// showSearch
// disabled={slackDisabled}
// filterOption={true}
// notFoundContent={null}
// loading={slackChannelsLoading}
// options={slackChannelOptions}

export function LemonMultiSelect<O extends LemonMultiSelectOptions>({
    value,
    onChange,
    options,
    disabled,
    placeholder,
}: LemonMultiSelectProps<O>): JSX.Element {
    const antOptions = Object.entries(options || {}).map(([key, option]) => ({
        key: key,
        value: key,
        label: option.label,
    }))

    return (
        <div className="LemonMultiSelect">
            <Select
                mode="tags"
                disabled={disabled}
                onChange={(v) => onChange?.(v)}
                tokenSeparators={[',']}
                value={value ? value : []}
                dropdownRender={(menu) => <div className="LemonMultiSelectDropdown">{menu}</div>}
                options={antOptions}
                placeholder={placeholder}
                tagRender={({ label, value, onClose }) => <LemonSnack onClose={onClose}>{label}</LemonSnack>}
            />
        </div>
    )
}
