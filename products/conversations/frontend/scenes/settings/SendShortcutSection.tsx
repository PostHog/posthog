import { useActions, useValues } from 'kea'

import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { conversationsSendOnEnterLogic } from './conversationsSendOnEnterLogic'

export function SendShortcutSection(): JSX.Element {
    const { sendOnEnter } = useValues(conversationsSendOnEnterLogic)
    const { setSendOnEnter } = useActions(conversationsSendOnEnterLogic)

    return (
        <SceneSection
            title="Send shortcut"
            titleSize="sm"
            className="my-8"
            description="Chooses which key sends a reply from the ticket composer. This applies to you, in this browser."
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <div className="flex items-center gap-4 justify-between">
                    <div>
                        <label htmlFor="conversations-send-on-enter" className="font-medium">
                            Send with Enter
                        </label>
                        <p className="text-xs text-muted-alt mb-0">
                            When on, Enter sends the reply and Shift+Enter adds a new line. When off, Enter adds a new
                            line. Cmd/Ctrl+Enter sends either way.
                        </p>
                    </div>
                    <LemonSwitch id="conversations-send-on-enter" checked={sendOnEnter} onChange={setSendOnEnter} />
                </div>
            </LemonCard>
        </SceneSection>
    )
}
