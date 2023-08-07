import './HelpButton.scss'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import type { helpButtonLogicType } from './HelpButtonType'
import {
    IconArrowDropDown,
    IconArticle,
    IconHelpOutline,
    IconQuestionAnswer,
    IconMessages,
    IconFlare,
    IconLive,
    IconSupport,
    IconFeedback,
    IconBugReport,
} from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { Placement } from '@floating-ui/react'
import { DefaultAction, inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { hedgehogbuddyLogic } from '../HedgehogBuddy/hedgehogbuddyLogic'
import { HedgehogBuddyWithLogic } from '../HedgehogBuddy/HedgehogBuddy'
import { supportLogic } from '../Support/supportLogic'
import { SupportModal } from '../Support/SupportModal'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

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
}: HelpButtonProps): JSX.Element | null {
    const { reportHelpButtonUsed } = useActions(eventUsageLogic)
    const { isHelpVisible } = useValues(helpButtonLogic({ key: customKey }))
    const { toggleHelp, hideHelp } = useActions(helpButtonLogic({ key: customKey }))
    const { validProductTourSequences } = useValues(inAppPromptLogic)
    const { runFirstValidSequence, promptAction } = useActions(inAppPromptLogic)
    const { isPromptVisible } = useValues(inAppPromptLogic)
    const { hedgehogModeEnabled } = useValues(hedgehogbuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogbuddyLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    const showSupportOptions: boolean = preflight?.cloud || false

    if (contactOnly && !showSupportOptions) {
        return null // We don't offer support for self-hosted instances
    }

    return (
        <>
            <LemonMenu
                items={[
                    !contactOnly && {
                        items: [
                            {
                                icon: <IconLive />,
                                label: "What's new?",
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.Updates)
                                    hideHelp()
                                },
                                to: 'https://posthog.com/changelog',
                                targetBlank: true,
                            },
                        ],
                    },
                    showSupportOptions && {
                        items: [
                            {
                                label: 'Ask on the forum',
                                icon: <IconQuestionAnswer />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.Slack)
                                    hideHelp()
                                },
                                to: `https://posthog.com/questions${HELP_UTM_TAGS}`,
                                targetBlank: true,
                            },
                            {
                                label: 'Report a bug',
                                icon: <IconBugReport />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.SupportForm)
                                    openSupportForm('bug')
                                    hideHelp()
                                },
                            },
                            {
                                label: 'Give feedback',
                                icon: <IconFeedback />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.SupportForm)
                                    openSupportForm('feedback')
                                    hideHelp()
                                },
                            },
                            {
                                label: 'Get support',
                                icon: <IconSupport />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.SupportForm)
                                    openSupportForm('support')
                                    hideHelp()
                                },
                            },
                        ],
                    },
                    !contactOnly && {
                        items: [
                            {
                                label: 'Read the docs',
                                icon: <IconArticle />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.Docs)
                                    hideHelp()
                                },
                                to: `https://posthog.com/docs${HELP_UTM_TAGS}`,
                                targetBlank: true,
                            },
                            validProductTourSequences.length > 0 && {
                                label: isPromptVisible ? 'Stop tutorial' : 'Explain this page',
                                icon: <IconMessages />,
                                onClick: () => {
                                    if (isPromptVisible) {
                                        promptAction(DefaultAction.SKIP)
                                    } else {
                                        runFirstValidSequence({ runDismissedOrCompleted: true })
                                    }
                                    hideHelp()
                                },
                            },
                            {
                                label: `${hedgehogModeEnabled ? 'Disable' : 'Enable'} hedgehog mode`,
                                icon: <IconFlare />,
                                onClick: () => {
                                    setHedgehogModeEnabled(!hedgehogModeEnabled)
                                    hideHelp()
                                },
                            },
                        ],
                    },
                ]}
                onVisibilityChange={(visible) => !visible && hideHelp()}
                visible={isHelpVisible}
                placement={placement}
                actionable
                onClickOutside={hideHelp}
            >
                <div className={clsx('help-button', inline && 'inline')} onClick={toggleHelp} data-attr="help-button">
                    {customComponent || (
                        <>
                            <IconHelpOutline />
                            <IconArrowDropDown />
                        </>
                    )}
                </div>
            </LemonMenu>
            <HedgehogBuddyWithLogic />
            <SupportModal />
        </>
    )
}
