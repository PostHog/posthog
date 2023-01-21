import React, { useState } from 'react'
import { Modal, Button, Card, Row, Col } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { AuthorizedUrls } from 'scenes/toolbar-launch/AuthorizedUrls'
import { IconEdit } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function NewActionButton(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [appUrlsVisible, setAppUrlsVisible] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <LemonButton type="primary" onClick={() => setVisible(true)} data-attr="create-action">
                New {featureFlags[FEATURE_FLAGS.SIMPLIFY_ACTIONS] ? 'Calculated Event' : 'Action'}
            </LemonButton>
            <Modal
                visible={visible}
                style={{ cursor: 'pointer' }}
                onCancel={() => {
                    setVisible(false)
                    setAppUrlsVisible(false)
                }}
                title={`Create new ${featureFlags[FEATURE_FLAGS.SIMPLIFY_ACTIONS] ? 'calculated event' : 'action'}`}
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
                                    <IconEdit />
                                </div>
                            </Card>
                        </Col>
                    </Row>
                )}
                {appUrlsVisible && <AuthorizedUrls />}
            </Modal>
        </>
    )
}
