import React from 'react'
import './HelpButton.scss'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import { helpButtonLogicType } from './HelpButtonType'
import { Popup } from '../Popup/Popup'
import { Placement } from '@popperjs/core'
import { LemonButton } from '../LemonButton'
import { IconArrowDropDown, IconArticle, IconGithub, IconHelpOutline, IconMail, IconQuestionAnswer } from '../icons'
import clsx from 'clsx'

const HELP_UTM_TAGS = '?utm_medium=in-product&utm_campaign=help-button-top'

export const helpButtonLogic = kea<helpButtonLogicType>({
    path: ['lib', 'components', 'HelpButton', 'HelpButton'],
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
    customComponent?: JSX.Element
    inline?: boolean // Whether the component should be an inline element as opposed to a block element
}

export function HelpButton({ placement, customComponent, inline }: HelpButtonProps): JSX.Element {
    const { reportHelpButtonUsed } = useActions(eventUsageLogic)
    const { isHelpVisible } = useValues(helpButtonLogic)
    const { toggleHelp, hideHelp } = useActions(helpButtonLogic)

    return (
        <Popup
            overlay={
                <>
                    <a href={`https://posthog.com/slack${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                        <LemonButton
                            icon={<IconQuestionAnswer />}
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
                    <a href="https://github.com/PostHog/posthog/issues/new/choose" rel="noopener" target="_blank">
                        <LemonButton
                            icon={<IconGithub />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.GitHub)
                                hideHelp()
                            }}
                        >
                            Create an issue on GitHub
                        </LemonButton>
                    </a>
                    <a href="mailto:hey@posthog.com" target="_blank">
                        <LemonButton
                            icon={<IconMail />}
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
                            icon={<IconArticle />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Docs)
                                hideHelp()
                            }}
                        >
                            Read the docs
                        </LemonButton>
                    </a>
                </>
            }
            onClickOutside={hideHelp}
            visible={isHelpVisible}
            placement={placement}
            actionable
        >
            <div
                className={clsx('help-button', customComponent && 'custom-component', inline && 'inline')}
                onClick={toggleHelp}
            >
                {customComponent || (
                    <>
                        <IconHelpOutline />
                        <IconArrowDropDown />
                    </>
                )}
            </div>
        </Popup>
    )
}
