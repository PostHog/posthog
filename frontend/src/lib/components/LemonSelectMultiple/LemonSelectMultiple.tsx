import { Select } from 'antd'
import React from 'react'
import { LemonSnack } from '../LemonSnack/LemonSnack'
import './LemonSelectMultiple.scss'

export interface LemonSelectMultipleOption {
    label: string | React.ReactNode
    disabled?: boolean
    'data-attr'?: string
}

export interface LemonSelectMultipleOptionItem extends LemonSelectMultipleOption {
    key: string
}

export type LemonSelectMultipleOptions = Record<string, LemonSelectMultipleOption>

export interface LemonSelectMultipleProps {
    options?: LemonSelectMultipleOptions | LemonSelectMultipleOptionItem[]
    value?: string[] | null
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    onChange?: (newValue: string[]) => void
    onSearch?: (value: string) => void
    filterOption?: boolean
    mode?: 'single' | 'multiple' | 'multiple-custom'
    'data-attr'?: string
}

export function LemonSelectMultiple({
    value,
    options,
    disabled,
    loading,
    placeholder,
    onChange,
    onSearch,
    filterOption = true,
    mode = 'single',
    ...props
}: LemonSelectMultipleProps): JSX.Element {
    const optionsAsList: LemonSelectMultipleOptionItem[] = Array.isArray(options)
        ? options
        : Object.entries(options || {}).map(([key, option]) => ({
              key: key,
              ...option,
          }))

    const antOptions = optionsAsList.map((option) => ({
        key: option.key,
        value: option.key,
        label: option.label,
    }))

    return (
        <div className="LemonSelectMultiple" {...props}>
            <Select
                mode={mode === 'multiple' ? 'multiple' : mode === 'multiple-custom' ? 'tags' : undefined}
                showSearch
                disabled={disabled}
                loading={loading}
                onSearch={onSearch}
                onChange={(v) => onChange?.(v)}
                tokenSeparators={[',']}
                value={value ? value : []}
                dropdownRender={(menu) => <div className="LemonSelectMultipleDropdown">{menu}</div>}
                options={antOptions}
                placeholder={placeholder}
                notFoundContent={<></>}
                filterOption={filterOption}
                tagRender={({ label, onClose }) => <LemonSnack onClose={onClose}>{label}</LemonSnack>}
            />
        </div>
    )
}
