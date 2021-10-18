import './PathClean.scss'
import React from 'react'
import { Col, Input, Divider, Button, Row } from 'antd'

interface PathRegexPopupProps {
    onComplete: () => void
}

export function PathRegexPopup({ onComplete }: PathRegexPopupProps): JSX.Element {
    return (
        <div className="regex-popup">
            <Col>
                <b>New Wildcard</b>
                <Divider style={{ marginTop: 10, marginBottom: 10 }} />
                <span>Alias</span>
                <Input
                    defaultValue={''}
                    onPressEnter={() => {
                        return false
                    }}
                    style={{ marginTop: 8, marginBottom: 12 }}
                />
                <span>Regex</span>
                <Input
                    defaultValue={''}
                    onPressEnter={() => {
                        return false
                    }}
                    style={{ marginTop: 8 }}
                />
                <Row style={{ width: '100%', display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
                    <Button onClick={onComplete} type="link">
                        {' '}
                        Cancel{' '}
                    </Button>
                    <Button onClick={onComplete} type="primary">
                        {' '}
                        Save{' '}
                    </Button>
                </Row>
            </Col>
        </div>
    )
}
