import React from 'react'
import { Menu, Dropdown, Row, Col } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import './cohort.scss'

function SelectItem({
    Icon,
    text,
    description,
    onClick,
}: {
    Icon: React.ComponentType
    text: string
    description: string
    onClick: () => void
}): JSX.Element {
    return (
        <div onClick={onClick}>
            <Row align={'middle'}>
                <Icon />
                <div style={{ fontSize: 14, fontWeight: 'bold', marginLeft: 4 }}>{text}</div>
            </Row>
            <div style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.5)' }}>{description}</div>
        </div>
    )
}

export const STATIC = 'static'
export const DYNAMIC = 'dynamic'

export function CohortTypeSelector({
    type,
    onTypeChange,
}: {
    type: string
    onTypeChange: (type: string) => void
}): JSX.Element {
    const options = {
        [`${STATIC}`]: {
            text: 'Static',
            description: 'Upload a list of users. Updates manually',
            onClick: () => onTypeChange(STATIC),
        },
        [`${DYNAMIC}`]: {
            text: 'Dynamic',
            description: 'Cohort updates dynamically based on properties',
            onClick: () => onTypeChange(DYNAMIC),
        },
    }

    const menu = (
        <Menu>
            <Menu.Item key="0">
                <SelectItem
                    Icon={() => <DownOutlined />}
                    text={options[DYNAMIC].text}
                    description={options[DYNAMIC].description}
                    onClick={options[DYNAMIC].onClick}
                />
            </Menu.Item>
            <Menu.Item key="1">
                <SelectItem
                    Icon={() => <DownOutlined />}
                    text={options[STATIC].text}
                    description={options[STATIC].description}
                    onClick={options[STATIC].onClick}
                />
            </Menu.Item>
        </Menu>
    )

    return (
        <Col>
            <span className="sub-header">Type of cohort</span>
            <Dropdown overlay={menu} trigger={['click']}>
                <div
                    style={{
                        padding: 10,
                        border: '1px solid rgba(0, 0, 0, 0.3)',
                        borderRadius: 4,
                        maxWidth: 300,
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        cursor: 'pointer',
                    }}
                    onClick={(e) => e.preventDefault()}
                >
                    <div style={{ flex: 5 }}>
                        <SelectItem
                            Icon={() => <DownOutlined />}
                            text={options[type].text}
                            description={options[type].description}
                            onClick={options[type].onClick}
                        />
                    </div>
                    <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                        <DownOutlined />
                    </div>
                </div>
            </Dropdown>
        </Col>
    )
}
