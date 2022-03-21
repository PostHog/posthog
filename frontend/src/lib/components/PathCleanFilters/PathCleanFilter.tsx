import './PathClean.scss'
import React, { useState } from 'react'
import { Col, Input, Divider, Button, Row } from 'antd'

interface PathRegexPopupProps {
    onComplete: (newItem: Record<string, any>) => void
    onClose: () => void
    item: Record<string, any>
}

export function PathRegexPopup({ item, onComplete, onClose }: PathRegexPopupProps): JSX.Element {
    const [alias, setAlias] = useState(item['alias'])
    const [regex, setRegex] = useState(item['regex'])

    return (
        <div className="regex-popup">
            <Col>
                <b>New Wildcard</b>
                <Divider style={{ marginTop: 10, marginBottom: 10 }} />
                <span>Alias</span>
                <Input
                    defaultValue={alias}
                    onChange={(e) => setAlias(e.target.value)}
                    onPressEnter={() => false}
                    style={{ marginTop: 8, marginBottom: 12 }}
                />
                <span>Regex</span>
                <Input
                    defaultValue={regex}
                    onChange={(e) => setRegex(e.target.value)}
                    onPressEnter={() => false}
                    style={{ marginTop: 8, marginBottom: 0, fontFamily: 'monospace' }}
                />
                <div className="text-muted" style={{ marginBottom: 12 }}>
                    For example: <code>\/merchant\/\d+\/dashboard$</code>
                </div>
                <Row style={{ width: '100%', justifyContent: 'flex-end', marginTop: 12 }}>
                    <Button onClick={onClose} type="link">
                        {' '}
                        Cancel{' '}
                    </Button>
                    <Button onClick={() => onComplete({ alias, regex })} type="primary">
                        {' '}
                        Save{' '}
                    </Button>
                </Row>
            </Col>
        </div>
    )
}
