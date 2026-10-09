import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { claudeSubscriptionLogic } from '../logics/claudeSubscriptionLogic'

/** The dialog that stores a Claude subscription token: a command to run, then a field for its output. */
export function ClaudeSubscriptionConnectModal(): JSX.Element {
    const { connectModalOpen, token, connectError, connecting } = useValues(claudeSubscriptionLogic)
    const { closeConnectModal, setToken, submitToken } = useActions(claudeSubscriptionLogic)

    return (
        <LemonModal
            isOpen={connectModalOpen}
            onClose={closeConnectModal}
            closable={!connecting}
            title="Connect Claude"
            description="Create a token for your Claude subscription in your terminal. Then paste the token here."
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeConnectModal}
                        disabledReason={connecting ? 'Connecting…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitToken}
                        loading={connecting}
                        disabledReason={!token.trim() ? 'Paste the token first' : undefined}
                        data-attr="cloud-agents-claude-connect-submit"
                    >
                        Connect
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">1. Run this command</h4>
                    <CodeSnippet language={Language.Bash} compact wrap thing="command">
                        claude setup-token
                    </CodeSnippet>
                    <p className="mb-0 text-xs text-secondary">
                        Sign in when the command asks you to. It prints a token that starts with <code>sk-ant-oat</code>
                        .
                    </p>
                    <p className="mb-0 text-xs text-secondary">
                        You need{' '}
                        <Link to="https://docs.claude.com/en/docs/claude-code/overview" target="_blank">
                            Claude Code
                        </Link>{' '}
                        and a paid Claude plan.
                    </p>
                </div>
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">2. Paste the token</h4>
                    <LemonInput
                        type="password"
                        className="ph-no-capture"
                        value={token}
                        onChange={setToken}
                        onPressEnter={submitToken}
                        placeholder="Paste your Claude token"
                        status={connectError ? 'danger' : undefined}
                        autoComplete="off"
                        spellCheck={false}
                        disabled={connecting}
                        data-attr="cloud-agents-claude-token-input"
                    />
                </div>
                {connectError ? <LemonBanner type="error">{connectError}</LemonBanner> : null}
                <LemonBanner type="info">
                    PostHog never shows your token. It stores the token encrypted and uses it only for your cloud agent
                    runs. You can disconnect at any time.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
