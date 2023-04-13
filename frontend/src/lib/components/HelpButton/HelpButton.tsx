import './HelpButton.scss'
import { kea, useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { HelpType } from '~/types'
import type { helpButtonLogicType } from './HelpButtonType'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import {
    IconArrowDropDown,
    IconArticle,
    IconHelpOutline,
    IconMail,
    IconQuestionAnswer,
    IconMessages,
    IconFlare,
    IconTrendingUp,
    IconLive,
} from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { Placement } from '@floating-ui/react'
import { DefaultAction, inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { hedgehogbuddyLogic } from '../HedgehogBuddy/hedgehogbuddyLogic'
import { HedgehogBuddyWithLogic } from '../HedgehogBuddy/HedgehogBuddy'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { supportLogic } from '../Support/supportLogic'
import SupportForm from '../Support/SupportForm'

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
    const { validProductTourSequences } = useValues(inAppPromptLogic)
    const { runFirstValidSequence, promptAction } = useActions(inAppPromptLogic)
    const { isPromptVisible } = useValues(inAppPromptLogic)
    const { hedgehogModeEnabled } = useValues(hedgehogbuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogbuddyLogic)
    const { toggleActivationSideBar } = useActions(navigationLogic)
    const { openSupportForm } = useActions(supportLogic)

    return (
        <>
            <Popover
                overlay={
                    <>
                        {!contactOnly && (
                            <LemonButton
                                icon={<IconLive />}
                                status="stealth"
                                fullWidth
                                onClick={() => {
                                    reportHelpButtonUsed(HelpType.Updates)
                                    hideHelp()
                                }}
                                to={`https://posthog.com/blog/categories/posthog-news`}
                                targetBlank
                            >
                                What's new?
                            </LemonButton>
                        )}
                        <LemonButton
                            icon={<IconMail />}
                            status="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.SupportForm)
                                openSupportForm()
                                hideHelp()
                            }}
                        >
                            Bug / Feedback
                        </LemonButton>
                        {!contactOnly && (
                            <LemonButton
                                icon={<IconArticle />}
                                status="stealth"
                                fullWidth
                                onClick={() => {
                                    reportHelpButtonUsed(HelpType.Docs)
                                    hideHelp()
                                }}
                                to={`https://posthog.com/docs${HELP_UTM_TAGS}`}
                                targetBlank
                            >
                                Read the docs
                            </LemonButton>
                        )}
                        <LemonButton
                            icon={<IconQuestionAnswer />}
                            status="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Slack)
                                hideHelp()
                            }}
                            to={`https://posthog.com/questions${HELP_UTM_TAGS}`}
                            targetBlank
                        >
                            Ask us a question
                        </LemonButton>
                        <LemonButton
                            icon={<IconTrendingUp />}
                            status="stealth"
                            fullWidth
                            onClick={() => {
                                toggleActivationSideBar()
                                hideHelp()
                            }}
                        >
                            Open Quick Start
                        </LemonButton>
                        {validProductTourSequences.length > 0 && (
                            <LemonButton
                                icon={<IconMessages />}
                                status="stealth"
                                fullWidth
                                onClick={() => {
                                    if (isPromptVisible) {
                                        promptAction(DefaultAction.SKIP)
                                    } else {
                                        runFirstValidSequence({ runDismissedOrCompleted: true })
                                    }
                                    hideHelp()
                                }}
                            >
                                {isPromptVisible ? 'Stop tutorial' : 'Explain this page'}
                            </LemonButton>
                        )}
                        <LemonButton
                            icon={<IconFlare />}
                            status="stealth"
                            fullWidth
                            onClick={() => {
                                setHedgehogModeEnabled(!hedgehogModeEnabled)
                                hideHelp()
                            }}
                        >
                            {hedgehogModeEnabled ? 'Disable' : 'Enable'} Hedgehog Mode
                        </LemonButton>
                    </>
                }
                onClickOutside={hideHelp}
                visible={isHelpVisible}
                placement={placement}
                actionable
            >
                <div className={clsx('help-button', inline && 'inline')} onClick={toggleHelp} data-attr="help-button">
                    {customComponent || (
                        <>
                            <IconHelpOutline />
                            <IconArrowDropDown />
                        </>
                    )}
                </div>
            </Popover>
            <HedgehogBuddyWithLogic />
            <SupportForm />
        </>
    )
}
