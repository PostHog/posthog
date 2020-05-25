import React, { useState } from 'react'
import { Modal, Button, Card, Row, Col } from 'antd'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { SearchOutlined, EditOutlined } from '@ant-design/icons'
import { router } from 'kea-router'

export function NewActionButton() {
    let [visible, setVisible] = useState(false)
    let [appUrlsVisible, setAppUrlsVisible] = useState(false)
    return (
        <>
            <Button type="primary" onClick={() => setVisible(true)} data-attr="create-action">
                + New Action
            </Button>
            <Modal
                visible={visible}
                style={{ cursor: 'pointer' }}
                onCancel={() => setVisible(false)}
                title="Create new action"
                footer={<Button onClick={() => setVisible(true)}>Cancel</Button>}
            >
                <Row gutter={2} justify="space-between">
                    <Col xs={11}>
                        <Card title="Inspect element on your site" onClick={() => setAppUrlsVisible(true)} size="small">
                            <div style={{ textAlign: 'center', fontSize: 40 }}>
                                <SearchOutlined />
                            </div>
                        </Card>
                    </Col>
                    <Col xs={11}>
                        <Card
                            title="From event or pageview"
                            onClick={() => {
                                router.actions.push('/action')
                            }}
                            size="small"
                        >
                            <div style={{ textAlign: 'center', fontSize: 40 }} data-attr="new-action-pageview">
                                <EditOutlined />
                            </div>
                        </Card>
                    </Col>
                </Row>
            </Modal>
            <Modal
                visible={appUrlsVisible}
                onCancel={() => setAppUrlsVisible(false)}
                footer={<Button onClick={() => setAppUrlsVisible(true)}>Cancel</Button>}
            >
                <EditAppUrls allowNavigation={true} />
            </Modal>
        </>
    )
}
