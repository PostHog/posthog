import './LemonSelectMultiple.scss'

import { Select } from 'antd'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { range } from 'lib/utils'
import { ReactNode } from 'react'

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

export type LemonSelectMultipleProps = {
    selectClassName?: string
    options?: LemonSelectMultipleOptions | LemonSelectMultipleOptionItem[]
    value?: string | string[] | null
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    labelInValue?: boolean
    onSearch?: (value: string) => void
    onFocus?: () => void
    onBlur?: () => void
    filterOption?: boolean
    mode?: 'single' | 'multiple' | 'multiple-custom'
    onChange?: ((newValue: string) => void) | ((newValue: string[]) => void)
    'data-attr'?: string
}

export type LabelInValue = { value: string; label: ReactNode }

export function LemonSelectMultiple({
    value,
    options,
    disabled,
    loading,
    placeholder,
    labelInValue,
    onChange,
    onSearch,
    onFocus,
    onBlur,
    filterOption = true,
    mode = 'single',
    selectClassName,
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
        labelString: option.label,
    }))

    return (
        <div className="LemonSelectMultiple" {...props}>
            <Select
                className={selectClassName}
                mode={mode === 'multiple' ? 'multiple' : mode === 'multiple-custom' ? 'tags' : undefined}
                showSearch
                labelInValue={labelInValue}
                disabled={disabled}
                loading={loading}
                onSearch={onSearch}
                onFocus={onFocus}
                onBlur={onBlur}
                showAction={['focus']}
                onChange={(v) => {
                    if (onChange) {
                        // TRICKY: V is typed poorly and will be a string if the "mode" is undefined
                        if (!v || typeof v === 'string') {
                            const typedValues = v as string | null
                            const typedOnChange = onChange as (newValue: string | null) => void
                            typedOnChange(typedValues)
                        } else {
                            const typedValues = v.map((token) => token.toString().trim())
                            const typedOnChange = onChange as (newValue: string[]) => void
                            typedOnChange(typedValues)
                        }
                    }
                }}
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
                                    <LemonSkeleton.Circle className="w-6 h-6" />
                                    <LemonSkeleton />
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
