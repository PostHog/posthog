import React from 'react'
import { Menu, Dropdown, Row } from 'antd'
import { DownOutlined, CalculatorOutlined, OrderedListOutlined } from '@ant-design/icons'
import './CohortTypeSelector.scss'

export const STATIC = 'static'
export const DYNAMIC = 'dynamic'

type CohortTypeType = typeof STATIC | typeof DYNAMIC
interface SelectItemInterface {
    icon: JSX.Element
    text: string
    description: string
    onClick: () => void
}

function SelectItem({ icon, text, description, onClick }: SelectItemInterface): JSX.Element {
    return (
        <div onClick={onClick}>
            <Row align={'middle'}>
                {icon}
                <div style={{ fontSize: 14, fontWeight: 'bold', marginLeft: 4 }}>{text}</div>
            </Row>
            <div style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.5)' }}>{description}</div>
        </div>
    )
}

export function CohortTypeSelector({
    type,
    onTypeChange,
}: {
    type: CohortTypeType
    onTypeChange: (type: string) => void
}): JSX.Element {
    const options = [
        {
            key: STATIC,
            text: 'Static',
            description: 'Upload a list of users. Updates manually',
            onClick: () => onTypeChange(STATIC),
            icon: <OrderedListOutlined />,
        },
        {
            key: DYNAMIC,
            text: 'Dynamic',
            description: 'Cohort updates dynamically based on properties',
            onClick: () => onTypeChange(DYNAMIC),
            icon: <CalculatorOutlined />,
        },
    ]

    const menu = (
        <Menu>
            {options.map(({ key, ...props }) => (
                <Menu.Item key={key}>
                    <SelectItem {...props} />
                </Menu.Item>
            ))}
        </Menu>
    )

    const selectedOption = options.find((opt) => opt.key === type)

    return (
        <>
            <label className="ant-form-item-label">Type of Cohort</label>
            <Dropdown overlay={menu} trigger={['click']}>
                <div className="cohort-type-selector" onClick={(e) => e.preventDefault()}>
                    <div style={{ flexGrow: 1 }}>{selectedOption && <SelectItem {...selectedOption} />}</div>
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                        <DownOutlined />
                    </div>
                </div>
            </Dropdown>
        </>
    )
}
