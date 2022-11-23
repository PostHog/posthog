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
    IconFlare,
    IconTrendingUp,
} from '../icons'
import clsx from 'clsx'
import { Placement } from '@floating-ui/react-dom-interactions'
import { DefaultAction, inAppPromptLogic } from 'lib/logic/inAppPrompt/inAppPromptLogic'
import { hedgehogbuddyLogic } from '../HedgehogBuddy/hedgehogbuddyLogic'
import { HedgehogBuddyWithLogic } from '../HedgehogBuddy/HedgehogBuddy'

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

    return (
        <>
            <Popup
                overlay={
                    <>
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
                            icon={<IconGithub />}
                            status="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.GitHub)
                                hideHelp()
                            }}
                            to={`https://github.com/PostHog/posthog/issues/new/choose`}
                            targetBlank
                        >
                            Create an issue on GitHub
                        </LemonButton>
                        <LemonButton
                            icon={<IconMail />}
                            status="stealth"
                            fullWidth
                            onClick={() => {
                                reportHelpButtonUsed(HelpType.Email)
                                hideHelp()
                            }}
                            to={'mailto:hey@posthog.com'}
                            targetBlank
                        >
                            Send us an email
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
                        {!isPromptVisible && (
                            <LemonButton
                                icon={<IconTrendingUp />}
                                status="stealth"
                                fullWidth
                                onClick={() => {
                                    promptAction('activation-checklist')
                                    hideHelp()
                                }}
                            >
                                How to be successful with PostHog
                            </LemonButton>
                        )}
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
            </Popup>
            <HedgehogBuddyWithLogic />
        </>
    )
}
