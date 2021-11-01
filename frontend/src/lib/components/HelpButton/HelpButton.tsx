import React from 'react'
import './HelpButton.scss'
import { QuestionCircleOutlined, MailOutlined, SolutionOutlined, CaretDownOutlined } from '@ant-design/icons'
import { Button, Popover, Row } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import slackLogo from 'public/slack-logo.svg'
import { helpButtonLogicType } from './HelpButtonType'
import { TooltipPlacement } from 'antd/lib/tooltip'

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

export interface HelpButtonProps {
    withCaret?: boolean
    placement?: TooltipPlacement
    customComponent?: JSX.Element
}

export function HelpButton({ customComponent, withCaret = false, placement }: HelpButtonProps): JSX.Element {
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
                placement={placement}
            >
                <Row align="middle">
                    {customComponent || (
                        <>
                            <QuestionCircleOutlined className="help-icon" />
                            {withCaret && <CaretDownOutlined />}
                        </>
                    )}
                </Row>
            </Popover>
        </div>
    )
}
