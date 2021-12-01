import React, { useState } from 'react'
import { Modal, Button, Card, Row, Col } from 'antd'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { SearchOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export function NewActionButton(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [appUrlsVisible, setAppUrlsVisible] = useState(false)

    return (
        <>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setVisible(true)} data-attr="create-action">
                New Action
            </Button>
            <Modal
                visible={visible}
                style={{ cursor: 'pointer' }}
                onCancel={() => {
                    setVisible(false)
                    setAppUrlsVisible(false)
                }}
                title="Create new action"
                footer={[
                    appUrlsVisible && (
                        <Button key="back-button" onClick={() => setAppUrlsVisible(false)}>
                            Back
                        </Button>
                    ),
                    <Button
                        key="cancel-button"
                        onClick={() => {
                            setVisible(false)
                            setAppUrlsVisible(false)
                        }}
                    >
                        Cancel
                    </Button>,
                ]}
            >
                {!appUrlsVisible && (
                    <Row gutter={2} justify="space-between">
                        <Col xs={11}>
                            <Card
                                title="Inspect element on your site"
                                onClick={() => setAppUrlsVisible(true)}
                                size="small"
                            >
                                <div style={{ textAlign: 'center', fontSize: 40 }}>
                                    <SearchOutlined />
                                </div>
                            </Card>
                        </Col>
                        <Col xs={11}>
                            <Card
                                title="From event or pageview"
                                onClick={() => {
                                    router.actions.push(urls.createAction())
                                }}
                                size="small"
                            >
                                <div style={{ textAlign: 'center', fontSize: 40 }} data-attr="new-action-pageview">
                                    <EditOutlined />
                                </div>
                            </Card>
                        </Col>
                    </Row>
                )}
                {appUrlsVisible && <EditAppUrls allowNavigation />}
            </Modal>
        </>
    )
}
