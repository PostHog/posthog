import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { useInterval } from 'lib/hooks/useInterval'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Button, Row, Space, Popconfirm, Dropdown, Menu, Typography } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { DownOutlined, SlackSquareOutlined, ReadOutlined, UserAddOutlined } from '@ant-design/icons'
import { teamLogic } from 'scenes/teamLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { PanelSupport } from './PanelComponents'
import './Panels.scss'

const { Text } = Typography

export function VerificationPanel(): JSX.Element {
    const { loadCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setVerify, completeOnboarding } = useActions(ingestionLogic)
    const { index } = useValues(ingestionLogic)
    const [isPopConfirmShowing, setPopConfirmShowing] = useState(false)
    const [isHelpMenuShowing, setHelpMenuShowing] = useState(false)
    const { showInviteModal } = useActions(inviteLogic)

    useInterval(() => {
        if (!currentTeam?.ingested_event && !isPopConfirmShowing && !isHelpMenuShowing) {
            loadCurrentTeam()
        }
    }, 2000)

    function HelperButtonRow(): JSX.Element {
        function HelpButton(): JSX.Element {
            const menu = (
                <Menu selectable>
                    <Menu.Item key="0" data-attr="ingestion-help-item-docs">
                        <a href="https://posthog.com/docs/integrate/ingest-live-data" target="_blank">
                            <Button type="link">
                                <ReadOutlined />
                                Read the ingestion docs
                            </Button>
                        </a>
                    </Menu.Item>
                    <Menu.Item key="1" data-attr="ingestion-help-item-invite">
                        <Button type="link" onClick={showInviteModal}>
                            <UserAddOutlined />
                            Invite team member
                        </Button>
                    </Menu.Item>
                    <Menu.Item key="2" data-attr="ingestion-help-item-slack">
                        <a href="https://posthog.com/slack?s=app" target="_blank">
                            <Button type="link">
                                <SlackSquareOutlined />
                                Ask us in Slack
                            </Button>
                        </a>
                    </Menu.Item>
                </Menu>
            )
            return (
                <Dropdown
                    overlay={menu}
                    trigger={['click']}
                    visible={isHelpMenuShowing}
                    onVisibleChange={(v) => {
                        setHelpMenuShowing(v)
                    }}
                >
                    <Button type="primary" data-attr="ingestion-help-button" onClick={() => setHelpMenuShowing(true)}>
                        Need help? <DownOutlined />
                    </Button>
                </Dropdown>
            )
        }

        const popoverTitle = (
            <Space direction="vertical">
                <Text strong>Are you sure you want to continue without data?</Text>
                <Text>You won't be able to conduct analysis or use most tools without event data.</Text>
                <Text>For the best experience, we recommend adding event data before continuing.</Text>
            </Space>
        )
        return (
            <Space style={{ float: 'right' }}>
                <Popconfirm
                    title={popoverTitle}
                    okText="Yes, I know what I'm doing."
                    okType="danger"
                    cancelText="No, go back."
                    onVisibleChange={(v) => {
                        setPopConfirmShowing(v)
                    }}
                    onCancel={() => {
                        setPopConfirmShowing(false)
                    }}
                    visible={isPopConfirmShowing}
                    onConfirm={completeOnboarding}
                    cancelButtonProps={{ type: 'primary' }}
                >
                    <Button
                        type="dashed"
                        data-attr="ingestion-continue-anyway"
                        onClick={() => {
                            setPopConfirmShowing(true)
                        }}
                    >
                        Continue without verifying
                    </Button>
                </Popconfirm>
                <HelpButton />
            </Space>
        )
    }

    return (
        <CardContainer index={index} onBack={() => setVerify(false)}>
            <div style={{ paddingLeft: 24, paddingRight: 24 }}>
                {!currentTeam?.ingested_event ? (
                    <>
                        <div className="ingestion-listening-for-events">

                            <Spinner size="lg" />
                            <h1 className="ingestion-title pt">Listening for events...</h1>
                            <p className="prompt-text">
                                Once you have integrated the snippet and sent an event, we will verify it was properly received
                                and continue.
                            </p>
                            <LemonButton fullWidth center type="secondary" onClick={completeOnboarding}>
                                Continue without verifying
                            </LemonButton>
                        </div>
                        <PanelSupport />
                        {/* <Row className="flex-center">
                            <Spinner style={{ marginRight: 4 }} />
                            <h2 className="ml-3" style={{ marginBottom: 0, color: 'var(--primary-alt)' }}>
                                Listening for events...
                            </h2>
                        </Row>
                        <p className="prompt-text mt-05">
                            Once you have integrated the snippet and sent an event, we will verify it was properly received
                            and continue.
                        </p>
                        <HelperButtonRow /> */}
                    </>
                ) : (
                    <>
                        <h1 className="ingestion-title">Successfully sent events!</h1>
                        <p className="prompt-text text-muted">
                            You will now be able to explore PostHog and take advantage of all its features to understand
                            your users.
                        </p>
                        {/* <Button
                        data-attr="wizard-complete-button"
                        type="primary"
                        style={{ float: 'right' }}
                        onClick={completeOnboarding}
                    >
                        Complete
                    </Button> */}
                        <div className='mb' style={{ paddingTop: 24, borderTop: '2px dashed var(--border)' }}>
                            <LemonButton
                                data-attr="wizard-complete-button"
                                type="primary"
                                onClick={completeOnboarding}
                                fullWidth
                                center
                            >
                                Continue to PostHog
                            </LemonButton>
                        </div>
                        <PanelSupport />
                    </>
                )}
            </div>

        </CardContainer>
    )
}
