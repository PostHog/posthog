import { offset } from '@floating-ui/react'
import { IconArrowRight, IconRewind } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiFilterLogic } from './aiFilterLogic'

export function AiFilterInput(): JSX.Element {
    const mountedLogic = useMountedLogic(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters } = useActions(mountedLogic)
    const filterLogic = aiFilterLogic({ setFilters, resetFilters })
    const { messages, input, isLoading } = useValues(filterLogic)
    const { setInput, handleSend, handleReset } = useActions(filterLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    return (
        <>
            <div className="w-[min(44rem,100%)] relative">
                <LemonTextArea
                    value={input}
                    onChange={(value) => setInput(value)}
                    placeholder={
                        isLoading
                            ? 'Thinking…'
                            : messages.length === 0
                            ? 'Show me recordings of people who ...'
                            : 'Ask follow-up'
                    }
                    onPressEnter={() => {
                        if (input) {
                            handleSend()
                        }
                    }}
                    minRows={1}
                    maxRows={10}
                    className="p-3"
                    autoFocus
                    disabled={isLoading}
                />
                <div className="absolute top-0 bottom-0 flex items-center right-2">
                    <AIConsentPopoverWrapper placement="right-end" middleware={[offset(-12)]} showArrow>
                        <LemonButton
                            type={messages.length === 0 ? 'primary' : 'secondary'}
                            onClick={handleSend}
                            tooltip="Let's go!"
                            disabled={isLoading || input.length === 0 || !dataProcessingAccepted}
                            size="small"
                            icon={<IconArrowRight />}
                        />
                    </AIConsentPopoverWrapper>
                </div>
            </div>
            <span className="text-xs text-muted-alt">
                * Max AI currently only knows about PostHog default properties added by our SDKs. For your custom
                properties, use the filters box below.
            </span>
            {messages.length > 0 && (
                <div>
                    <LemonButton
                        icon={<IconRewind />}
                        onClick={handleReset}
                        disabled={isLoading}
                        type="tertiary"
                        size="xsmall"
                    >
                        Start over
                    </LemonButton>
                </div>
            )}
        </>
    )
}
