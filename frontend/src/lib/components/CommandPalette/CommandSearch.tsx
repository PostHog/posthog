import React from 'react'
import { Input, Row } from 'antd'
import { SearchOutlined } from '@ant-design/icons'

export function CommandSearch(): JSX.Element {
    return (
        <Row
            style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'center',
                alignItems: 'center',
                width: '100%',
                paddingTop: 20,
                paddingLeft: 25,
                paddingRight: 25,
            }}
        >
            <Input
                size="large"
                prefix={
                    <SearchOutlined
                        placeholder="What would you like to do? (e.g. Go to default dashboard)"
                        style={{ marginRight: 10 }}
                    ></SearchOutlined>
                }
                bordered={false}
            ></Input>
        </Row>
    )
}
