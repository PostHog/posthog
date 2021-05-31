import React from 'react'
import { Menu, Dropdown, Row, Col } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import './cohort.scss'

function SelectItem({
    Icon,
    text,
    description,
}: {
    Icon: React.ComponentType
    text: string
    description: string
}): JSX.Element {
    return (
        <div>
            <Row align={'middle'}>
                <Icon />
                <div>{text}</div>
            </Row>
            <div>{description}</div>
        </div>
    )
}

const menu = (
    <Menu>
        <Menu.Item key="0">
            <SelectItem
                Icon={() => <DownOutlined />}
                text={'Dynamic'}
                description={'Cohort updates dynamically based on properties'}
             />
        </Menu.Item>
        <Menu.Item key="1">
            <SelectItem
                Icon={() => <DownOutlined />}
                text={'Static'}
                description={'Upload a list of users. Updates manually'}
             />
        </Menu.Item>
    </Menu>
)

export function CohortTypeSelector(): JSX.Element {
    return (
        <Col>
            <span className="header">Type of cohort</span>
            <Dropdown overlay={menu} trigger={['click']}>
                <div
                    style={{ padding: 10, border: '1px solid rgba(0, 0, 0, 0.3)', borderRadius: 4, maxWidth: 300 }}
                    onClick={(e) => e.preventDefault()}
                >
                    <Row align="middle">
                        <SelectItem
                            Icon={() => <DownOutlined />}
                            text={'Dynamic'}
                            description={'Cohort updates dynamically based on properties'}
                         />
                        <DownOutlined />
                    </Row>
                </div>
            </Dropdown>
        </Col>
    )
}
