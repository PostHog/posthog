import './HelpButton.scss'

import { Placement } from '@floating-ui/react'
import clsx from 'clsx'
import { actions, connect, kea, key, listeners, path, props, reducers, useActions, useValues } from 'kea'

import { IconBug, IconChevronDown, IconDocument, IconQuestion, IconSupport } from '@posthog/icons'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconFeedback, IconQuestionAnswer } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { HelpType } from '~/types'

import { supportLogic } from '../Support/supportLogic'
import type { helpButtonLogicType } from './HelpButtonType'

const HELP_UTM_TAGS = '?utm_medium=in-product&utm_campaign=help-button-top'

export const helpButtonLogic = kea<helpButtonLogicType>([
    props(
        {} as {
            key?: string
        }
    ),
    key((props: { key?: string }) => props.key || 'global'),
    path((key) => ['lib', 'components', 'HelpButton', key]),
    connect(() => ({
        actions: [eventUsageLogic, ['reportHelpButtonViewed']],
    })),
    actions({
        toggleHelp: true,
        showHelp: true,
        hideHelp: true,
    }),
    reducers({
        isHelpVisible: [
            false,
            {
                toggleHelp: (previousState) => !previousState,
                showHelp: () => true,
                hideHelp: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        showHelp: () => {
            actions.reportHelpButtonViewed()
        },
        toggleHelp: () => {
            if (values.isHelpVisible) {
                actions.reportHelpButtonViewed()
            }
        },
    })),
])

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
    const { openSupportForm } = useActions(supportLogic)
    const { isCloudOrDev } = useValues(preflightLogic)

    const showSupportOptions: boolean = isCloudOrDev || false

    if (contactOnly && !showSupportOptions) {
        return null // We don't offer support for self-hosted instances
    }

    return (
        <>
            <LemonMenu
                items={[
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
                                icon: <IconBug />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.SupportForm)
                                    openSupportForm({ kind: 'bug' })
                                    hideHelp()
                                },
                            },
                            {
                                label: 'Give feedback',
                                icon: <IconFeedback />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.SupportForm)
                                    openSupportForm({ kind: 'feedback' })
                                    hideHelp()
                                },
                            },
                            {
                                label: 'Get support',
                                icon: <IconSupport />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.SupportForm)
                                    openSupportForm({ kind: 'support' })
                                    hideHelp()
                                },
                            },
                        ],
                    },
                    !contactOnly && {
                        items: [
                            {
                                label: 'Read the docs',
                                icon: <IconDocument />,
                                onClick: () => {
                                    reportHelpButtonUsed(HelpType.Docs)
                                    hideHelp()
                                },
                                to: `https://posthog.com/docs${HELP_UTM_TAGS}`,
                                targetBlank: true,
                            },
                        ],
                    },
                ]}
                onVisibilityChange={(visible) => !visible && hideHelp()}
                visible={isHelpVisible}
                placement={placement}
                onClickOutside={hideHelp}
            >
                <div className={clsx('help-button', inline && 'inline')} onClick={toggleHelp} data-attr="help-button">
                    {customComponent || (
                        <>
                            <IconQuestion />
                            <IconChevronDown />
                        </>
                    )}
                </div>
            </LemonMenu>
        </>
    )
}
