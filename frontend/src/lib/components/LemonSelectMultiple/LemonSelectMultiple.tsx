import { Select, Skeleton } from 'antd'
import { range } from 'lib/utils'
import React from 'react'
import { LemonSnack } from '../LemonSnack/LemonSnack'
import './LemonSelectMultiple.scss'

export interface LemonSelectMultipleOption {
    label: string
    disabled?: boolean
    'data-attr'?: string
    labelComponent?: React.ReactNode
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
        label: option.labelComponent || option.label,
        labelString: option.label || option.key,
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
                optionFilterProp="labelString"
                options={antOptions}
                placeholder={placeholder}
                notFoundContent={
                    loading ? (
                        <div>
                            {range(5).map((x) => (
                                <div key={x} className="LemonSelectMultipleDropdown__skeleton">
                                    <Skeleton.Avatar shape="circle" size="small" active />
                                    <Skeleton paragraph={false} active />
                                </div>
                            ))}
                        </div>
                    ) : null
                }
                filterOption={filterOption}
                tagRender={({ label, onClose }) => <LemonSnack onClose={onClose}>{label}</LemonSnack>}
            />
        </div>
    )
}
