import { Select } from 'antd'
import React from 'react'
import { UserBasicType } from '~/types'
import { LemonSnack } from '../LemonSnack/LemonSnack'
import { ProfilePicture } from '../ProfilePicture'
import './LemonSelectSearch.scss'

export interface LemonSelectSearchOption {
    label: string | React.ReactNode
    disabled?: boolean
    'data-attr'?: string
}

export interface LemonSelectSearchOptionItem extends LemonSelectSearchOption {
    key: string
}

export type LemonSelectSearchOptions = Record<string, LemonSelectSearchOption>

export interface LemonSelectSearchProps {
    options?: LemonSelectSearchOptions | LemonSelectSearchOptionItem[]
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

export function LemonSelectSearch({
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
}: LemonSelectSearchProps): JSX.Element {
    const saneOptions: LemonSelectSearchOptionItem[] = Array.isArray(options)
        ? options
        : Object.entries(options || {}).map(([key, option]) => ({
              key: key,
              ...option,
          }))

    const antOptions = saneOptions.map((option) => ({
        key: option.key,
        value: option.key,
        label: option.label,
    }))

    return (
        <div className="LemonSelectSearch" {...props}>
            <Select
                mode={mode === 'multiple' ? 'multiple' : mode === 'multiple-custom' ? 'tags' : undefined}
                showSearch
                disabled={disabled}
                loading={loading}
                onSearch={onSearch}
                onChange={(v) => onChange?.(v)}
                tokenSeparators={[',']}
                value={value ? value : []}
                dropdownRender={(menu) => <div className="LemonSelectSearchDropdown">{menu}</div>}
                options={antOptions}
                placeholder={placeholder}
                notFoundContent={<></>}
                filterOption={filterOption}
                tagRender={({ label, onClose }) => <LemonSnack onClose={onClose}>{label}</LemonSnack>}
            />
        </div>
    )
}

export function usersLemonSelectOptions(
    users: UserBasicType[],
    key: 'email' | 'uuid' = 'email'
): LemonSelectSearchOptionItem[] {
    return users.map((user) => ({
        key: user[key],
        label: (
            <>
                <span className="flex gap-05 items-center">
                    <ProfilePicture name={user.first_name} email={user.email} size="sm" />
                    <span>
                        {user.first_name} <b>{`<${user.email}>`}</b>
                    </span>
                </span>
            </>
        ),
    }))
}
