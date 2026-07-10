import { BindLogic, useAsyncActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowRight, IconLock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { HOMEPAGE_TAB_ID } from './constants'

export function HomepageAiInput(): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { acceptDataProcessing } = useAsyncActions(maxGlobalLogic)

    const fallbackConversationId = useMemo(() => uuid(), [])
    const threadProps: MaxThreadLogicProps = {
        panelId: HOMEPAGE_TAB_ID,
        conversationId: threadLogicKey || fallbackConversationId,
        conversation,
    }

    if (!dataProcessingAccepted) {
        const isAdmin = !dataProcessingApprovalDisabledReason
        return (
            <div className="border border-primary rounded-lg bg-surface-primary p-4 flex flex-col gap-2">
                <p className="font-medium text-pretty m-0">
                    PostHog AI needs your approval to potentially process identifying user data with external AI
                    providers.
                </p>
                <p className="text-muted text-xs m-0">Your data won't be used for training third-party models.</p>
                {isAdmin ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => void acceptDataProcessing().catch(console.error)}
                        sideIcon={<IconArrowRight />}
                    >
                        I allow AI analysis in this organization
                    </LemonButton>
                ) : (
                    <LemonButton type="secondary" size="small" disabled sideIcon={<IconLock />}>
                        {dataProcessingApprovalDisabledReason}
                    </LemonButton>
                )}
            </div>
        )
    }

    return (
        <BindLogic logic={maxThreadLogic} props={threadProps}>
            <SidebarQuestionInput />
        </BindLogic>
    )
}
