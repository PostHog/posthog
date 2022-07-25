import React from 'react'
import './HelpButton.scss'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import type { helpButtonLogicType } from './HelpButtonType'
import { Popup } from '../Popup/Popup'
import { LemonButton } from '../LemonButton'
import {
    IconArrowDropDown,
    IconArticle,
    IconGithub,
    IconHelpOutline,
    IconMail,
    IconQuestionAnswer,
    IconMessages,
} from '../icons'
import clsx from 'clsx'
import { Placement } from '@floating-ui/react-dom-interactions'
import { inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'

const HELP_UTM_TAGS = '?utm_medium=in-product&utm_campaign=help-button-top'

export const helpButtonLogic = kea<helpButtonLogicType>({
    props: {} as {
        key?: string
    },
    key: (props: { key?: string }) => props.key || 'global',
    path: (key) => ['lib', 'components', 'HelpButton', key],
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
    customKey?: string
    /** Whether the component should be an inline element as opposed to a block element. */
    inline?: boolean
    /** Whether only options abount contact with PostHog should be shown (e.g. leaving docs out). */
    contactOnly?: boolean
}

export function HelpButton({
    placement,
    customComponent,
    customKey,
    inline = false,
    contactOnly = false,
}: HelpButtonProps): JSX.Element {
    const { reportHelpButtonUsed } = useActions(eventUsageLogic)
    const { isHelpVisible } = useValues(helpButtonLogic({ key: customKey }))
    const { toggleHelp, hideHelp } = useActions(helpButtonLogic({ key: customKey }))
    const { validSequences } = useValues(inAppPromptLogic)
    const { runFirstValidSequence, closePrompts } = useActions(inAppPromptLogic)
    const { isPromptVisible } = useValues(inAppPromptLogic)

    console.log(isPromptVisible)

    return (
        <Popup
            overlay={
                <>
                    <a href={`https://posthog.com/questions${HELP_UTM_TAGS}`} rel="noopener" target="_blank">
                        <LemonButton
                            icon={<IconQuestionAnswer />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Slack)
                                hideHelp()
                            }}
                        >
                            Ask us a question
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
                    {!contactOnly && (
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
                    )}
                    {validSequences.length > 0 && (
                        <LemonButton
                            icon={<IconMessages />}
                            type="stealth"
                            fullWidth
                            onClick={() => {
                                if (isPromptVisible) {
                                    closePrompts()
                                } else {
                                    runFirstValidSequence({ runDismissedOrCompleted: true, restart: true })
                                }
                                hideHelp()
                            }}
                        >
                            {isPromptVisible ? 'Stop tutorial' : 'Explain this page'}
                        </LemonButton>
                    )}
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
