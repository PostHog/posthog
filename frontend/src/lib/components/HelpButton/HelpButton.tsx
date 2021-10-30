import React from 'react'
import './HelpButton.scss'
import { QuestionCircleOutlined, MailOutlined, SolutionOutlined, CaretDownOutlined } from '@ant-design/icons'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import slackLogo from 'public/slack-logo.svg'
import { helpButtonLogicType } from './HelpButtonType'
import { Popup } from '../Popup/Popup'
import { Placement } from '@popperjs/core'
import { LemonButton } from '../LemonButton'

const HELP_UTM_TAGS = '?utm_medium=in-product&utm_campaign=help-button-top'

export const helpButtonLogic = kea<helpButtonLogicType>({
    connect: {
        actions: [eventUsageLogic, ['reportHelpButtonViewed']],
    },
    actions: {
        toggleHelp: true,
        showHelp: true,
        hideHelp: true,
    },
    reducers: {
        isHelpVisible: [
            false,
            {
                toggleHelp: (previousState) => !previousState,
                showHelp: () => true,
                hideHelp: () => false,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        showHelp: () => {
            actions.reportHelpButtonViewed()
        },
        toggleHelp: () => {
            if (values.isHelpVisible) {
                actions.reportHelpButtonViewed()
            }
        },
    }),
})

export interface HelpButtonProps {
    placement?: Placement
}

export function HelpButton({ placement }: HelpButtonProps): JSX.Element {
    const { reportHelpButtonUsed } = useActions(eventUsageLogic)
    const { isHelpVisible } = useValues(helpButtonLogic)
    const { toggleHelp, hideHelp } = useActions(helpButtonLogic)

    return (
        <Popup
            overlay={
                <>
                    <a href={`https://posthog.com/slack${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                        <LemonButton
                            icon={<img src={slackLogo} alt="" height="28" />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Slack)
                                hideHelp()
                            }}
                        >
                            Message us on Slack
                        </LemonButton>
                    </a>
                    <a href="mailto:hey@posthog.com" target="_blank">
                        <LemonButton
                            icon={<MailOutlined />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Email)
                                hideHelp()
                            }}
                        >
                            Send us an email
                        </LemonButton>
                    </a>
                    <a href={`https://posthog.com/docs${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                        <LemonButton
                            icon={<SolutionOutlined />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Docs)
                                hideHelp()
                            }}
                        >
                            Check out our docs
                        </LemonButton>
                    </a>
                </>
            }
            onClickOutside={hideHelp}
            visible={isHelpVisible}
            placement={placement}
            actionable
        >
            <div className="help-button" onClick={toggleHelp}>
                <QuestionCircleOutlined className="help-icon" />
                <CaretDownOutlined />
            </div>
        </Popup>
    )
}
