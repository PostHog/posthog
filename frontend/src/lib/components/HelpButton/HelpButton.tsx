import React from 'react'
import './HelpButton.scss'
import { QuestionCircleOutlined, MailOutlined, SolutionOutlined } from '@ant-design/icons'
import { Button, Popover } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import slackLogo from 'public/slack-logo.svg'
import { helpButtonLogicType } from './HelpButtonType'

export const helpButtonLogic = kea<helpButtonLogicType>({
    actions: {
        setVisible: (visible: boolean) => ({ visible }),
    },
    reducers: {
        isVisible: [
            false,
            {
                setVisible: (_, { visible }) => visible,
            },
        ],
    },
})

export function HelpButton(): JSX.Element {
    const UTM_TAGS = '?utm_medium=in-product&utm_campaign=help-button-top'
    const { reportHelpButtonUsed, reportHelpButtonViewed } = useActions(eventUsageLogic)
    const { isVisible } = useValues(helpButtonLogic)
    const { setVisible } = useActions(helpButtonLogic)

    const overlay = (
        <div className="help-button-overlay-inner">
            <h3>Get help now</h3>
            <div className="support-link">
                <Button
                    href={`https://posthog.com/slack${UTM_TAGS}`}
                    rel="noopener"
                    target="_blank"
                    icon={<img src={slackLogo} alt="" height="28" />}
                    style={{ paddingLeft: 6 }} // paddingLeft accounts for the padding in the Slack logo image
                    block
                    onClick={() => reportHelpButtonUsed(HelpType.Slack)}
                >
                    Message us on Slack
                </Button>
            </div>
            <div className="support-link">
                <Button
                    href="mailto:hey@posthog.com"
                    target="_blank"
                    icon={<MailOutlined />}
                    block
                    onClick={() => reportHelpButtonUsed(HelpType.Email)}
                >
                    Send us an email
                </Button>
            </div>
            <div className="support-link">
                <Button
                    href={`https://posthog.com/docs${UTM_TAGS}`}
                    rel="noopener"
                    target="_blank"
                    icon={<SolutionOutlined />}
                    block
                    onClick={() => reportHelpButtonUsed(HelpType.Docs)}
                >
                    Check out our docs
                </Button>
            </div>
        </div>
    )
    return (
        <div className="help-button">
            <Popover
                content={overlay}
                trigger="click"
                overlayClassName="help-button-overlay"
                arrowContent={<></>}
                onVisibleChange={(visible) => {
                    setVisible(visible)
                    if (visible) {
                        reportHelpButtonViewed()
                    }
                }}
                visible={isVisible}
            >
                <QuestionCircleOutlined className="help-icon" />
            </Popover>
        </div>
    )
}
