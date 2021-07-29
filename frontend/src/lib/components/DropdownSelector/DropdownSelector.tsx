/* Custom dropdown selector with an icon a help caption  */
import { DownOutlined } from '@ant-design/icons'
import { Dropdown, Menu, Row } from 'antd'
import React from 'react'
import './DropdownSelector.scss'

interface DropdownSelectorProps {
    label?: string
    value: string | null
    onValueChange: (value: string | null) => void
    options: DropdownOption[]
}

interface DropdownOption {
    key: string
    label: string
    description?: string
    icon: JSX.Element
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
            <Row align={'middle'}>
                {icon}
                <div style={{ fontSize: 14, fontWeight: 'bold', marginLeft: 4 }}>{label}</div>
            </Row>
            {description && <div style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.5)' }}>{description}</div>}
        </div>
    )
}

export function DropdownSelector({ label, value, onValueChange, options }: DropdownSelectorProps): JSX.Element {
    const selectedOption = options.find((opt) => opt.key === value)

    const menu = (
        <Menu>
            {options.map(({ key, ...props }) => (
                <Menu.Item key={key}>
                    <SelectItem {...props} onClick={() => onValueChange(key)} />
                </Menu.Item>
            ))}
        </Menu>
    )

    return (
        <>
            {label && <label className="ant-form-item-label">{label}</label>}
            <Dropdown overlay={menu} trigger={['click']}>
                <div className="dropdown-selector" onClick={(e) => e.preventDefault()}>
                    <div style={{ flexGrow: 1 }}>
                        {selectedOption && <SelectItem {...selectedOption} onClick={() => {}} />}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                        <DownOutlined />
                    </div>
                </div>
            </Dropdown>
        </>
    )
}
