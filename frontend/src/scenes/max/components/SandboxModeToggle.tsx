import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SPECIAL_MODES } from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'

/**
 * Standalone control for opting a conversation into the sandbox runtime. Rendered only when the
 * `PHAI_SANDBOX_MODE` flag is on. The runtime is stamped onto the conversation's `agent_runtime`
 * at create-time and never changes afterwards — so for a fresh conversation this acts as a toggle,
 * and once a conversation has started it stays locked as a read-only indicator of the runtime.
 */
export function SandboxModeToggle(): JSX.Element | null {
    const { isSandboxMode, conversation, threadMessageCount, contextDisabledReason } = useValues(maxThreadLogic)
    const { setIsSandboxMode } = useActions(maxThreadLogic)
    const sandboxModeEnabled = useFeatureFlag('PHAI_SANDBOX_MODE')

    const isSandboxRuntime = conversation?.agent_runtime === 'sandbox'
    const isActive = isSandboxRuntime || isSandboxMode
    const hasExistingMessages = threadMessageCount > 0

    const handleToggle = useCallback((): void => {
        const next = !isActive
        posthog.capture('phai sandbox toggled', { enabled: next })
        // The selected agent mode is kept — sandbox carries it through as a context note.
        setIsSandboxMode(next)
    }, [isActive, setIsSandboxMode])

    // Hide entirely for non-sandbox conversations that have already started — there's nothing to
    // toggle, and we only want to surface this as a locked indicator for actual sandbox runtimes.
    if (!sandboxModeEnabled || (hasExistingMessages && !isSandboxRuntime)) {
        return null
    }

    // Runtime is fixed once the conversation exists; until then `contextDisabledReason` still gates it.
    const disabledReason = hasExistingMessages
        ? 'Start a new conversation to change the runtime'
        : contextDisabledReason

    return (
        <LemonButton
            size="xxsmall"
            type="tertiary"
            icon={SPECIAL_MODES.sandbox.icon}
            active={isActive}
            onClick={handleToggle}
            disabledReason={disabledReason}
            tooltip={SPECIAL_MODES.sandbox.description}
            className="flex-shrink-0 border [&>span]:text-secondary"
        >
            <span className="flex items-center gap-1">
                {SPECIAL_MODES.sandbox.name}
                {SPECIAL_MODES.sandbox.alpha && (
                    <LemonTag size="small" type="danger">
                        ALPHA
                    </LemonTag>
                )}
            </span>
        </LemonButton>
    )
}
