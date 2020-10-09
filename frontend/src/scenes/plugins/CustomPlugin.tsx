import React from 'react'
import { Button, Col, Input, Row } from 'antd'

export function CustomPlugin(): JSX.Element {
    return (
        <div>
            <h1 className="page-header">Install Custom Plugin</h1>
            <p>
                Paste the URL of the <strong>Github Repository</strong> of a plugin to install it
            </p>

            <Row style={{ maxWidth: 600, width: '100%' }}>
                <Col style={{ flex: 1 }}>
                    <Input value="" placeholder="https://github.com/user/repo" />
                </Col>
                <Col>
                    <Button type="primary">Install</Button>
                </Col>
            </Row>
        </div>
    )
}
