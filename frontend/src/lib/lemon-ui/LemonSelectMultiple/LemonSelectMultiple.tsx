import { Select } from 'antd'
import { range } from 'lib/utils'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import './LemonSelectMultiple.scss'
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

export interface LemonSelectMultipleProps {
    selectClassName?: string
    options?: LemonSelectMultipleOptions | LemonSelectMultipleOptionItem[]
    value?: string[] | null | LabelInValue[]
    disabled?: boolean
    loading?: boolean
    placeholder?: string
    labelInValue?: boolean
    onChange?: ((newValue: string[]) => void) | ((newValue: LabelInValue[]) => void)
    onSearch?: (value: string) => void
    onFocus?: () => void
    onBlur?: () => void
    filterOption?: boolean
    mode?: 'single' | 'multiple' | 'multiple-custom'
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
                        if (labelInValue) {
                            const typedValues = v as LabelInValue[]
                            const typedOnChange = onChange as (newValue: LabelInValue[]) => void
                            typedOnChange(typedValues)
                        } else {
                            const typedValues = v.map((token) => token.toString().trim()) as string[]
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
