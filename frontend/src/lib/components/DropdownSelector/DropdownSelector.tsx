/* Custom dropdown selector with an icon a help caption  */
import { Dropdown, Menu, Row } from 'antd'
import clsx from 'clsx'
import React from 'react'
import { IconArrowDropDown } from '../icons'
import './DropdownSelector.scss'

interface DropdownSelectorProps {
    label?: string
    value: string | null
    onValueChange: (value: string) => void
    options: DropdownOption[]
    hideDescriptionOnDisplay?: boolean // Hides the description support text on the main display component (i.e. only shown in the dropdown menu)
    disabled?: boolean
    compact?: boolean
}

interface DropdownOption {
    key: string
    label: string
    description?: string
    icon: JSX.Element
    hidden?: boolean
}

interface SelectItemInterface {
    icon: JSX.Element
    label: string
    description?: string
    onClick: () => void
}

function SelectItem({ icon, label, description, onClick }: SelectItemInterface): JSX.Element {
    return (
        <div onClick={onClick}>
            <div className="flex items-center text-sm font-medium gap-2">
                {icon}
                <div>{label}</div>
            </div>
            {description && <div className="text-muted text-xs mt-1">{description}</div>}
        </div>
    )
}

export function DropdownSelector({
    label,
    value,
    onValueChange,
    options,
    hideDescriptionOnDisplay,
    disabled,
    compact,
}: DropdownSelectorProps): JSX.Element {
    const selectedOption = options.find((opt) => opt.key === value)

    const menu = (
        <Menu>
            {options.map(({ key, hidden, ...props }) => {
                if (hidden) {
                    return null
                }
                return (
                    <Menu.Item key={key}>
                        <SelectItem {...props} onClick={() => onValueChange(key)} />
                    </Menu.Item>
                )
            })}
        </Menu>
    )

    return (
        <>
            {label && <label className="ant-form-item-label">{label}</label>}
            <Dropdown overlay={menu} trigger={['click']} disabled={disabled}>
                <div
                    className={clsx('dropdown-selector', disabled && ' disabled', compact && 'compact')}
                    onClick={(e) => e.preventDefault()}
                >
                    <div className="grow">
                        {selectedOption && (
                            <SelectItem
                                {...selectedOption}
                                onClick={() => {}}
                                description={hideDescriptionOnDisplay ? undefined : selectedOption.description}
                            />
                        )}
                    </div>
                    <div className="dropdown-arrow">
                        <IconArrowDropDown />
                    </div>
                </div>
            </Dropdown>
        </>
    )
}
