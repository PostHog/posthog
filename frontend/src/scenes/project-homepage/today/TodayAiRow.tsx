import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import { TodayPromptRow } from './TodayPromptRow'
import { todayPromptsLogic } from './todayPromptsLogic'

const AI_ICON = { glyph: <IconSparkles /> }

export function TodayAiRow(): JSX.Element | null {
    const { aiEnabled, aiPromptDismissed, canEnableAi, aiAccessRequested, requestingAiAccess } =
        useValues(todayPromptsLogic)
    const { dismissPrompt, acceptDataProcessing, requestAiAccess } = useActions(todayPromptsLogic)

    if (aiEnabled || aiPromptDismissed) {
        return null
    }
    const notNow = (
        <Button size="sm" variant="link-muted" onClick={() => dismissPrompt('ai')} data-attr="today-ai-row-dismiss">
            Not now
        </Button>
    )
    if (canEnableAi) {
        return (
            <TodayPromptRow
                icon={AI_ICON}
                title="Turn on PostHog AI"
                meta="Get reports on what needs you, and fixes for them. You approve this for the whole organization."
                dataAttr="today-ai-row"
                actions={
                    <>
                        {notNow}
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                                void retryImport(() => import('scenes/settings/organization/aiConsentCopy')).then(
                                    ({ openAIConsentLegalDialog }) =>
                                        openAIConsentLegalDialog({ onConfirm: () => acceptDataProcessing() })
                                )
                            }
                            data-attr="today-ai-row-enable"
                        >
                            Turn on
                        </Button>
                    </>
                }
            />
        )
    }
    return (
        <TodayPromptRow
            icon={AI_ICON}
            title="PostHog AI is off"
            meta={
                aiAccessRequested
                    ? 'Request sent. Your organization admins can turn it on.'
                    : 'An organization admin can turn it on to get reports on what needs you.'
            }
            dataAttr="today-ai-row"
            actions={
                aiAccessRequested ? null : (
                    <>
                        {notNow}
                        <Button
                            size="sm"
                            variant="outline"
                            loading={requestingAiAccess}
                            onClick={() => requestAiAccess()}
                            data-attr="today-ai-row-request"
                        >
                            Ask an admin
                        </Button>
                    </>
                )
            }
        />
    )
}
