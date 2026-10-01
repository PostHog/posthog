import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

const LOGIN_COMMAND = 'mkdir -p ~/.codex-posthog && CODEX_HOME=~/.codex-posthog codex login'
const COPY_COMMAND = 'cat ~/.codex-posthog/auth.json'

export function CodexConnectModal(): JSX.Element {
    const { connectModalOpen, authFileText, connectError, connecting } = useValues(personalCodexIntegrationLogic)
    const { closeConnectModal, setAuthFileText, submitAuthFile } = useActions(personalCodexIntegrationLogic)

    return (
        <LemonModal
            isOpen={connectModalOpen}
            onClose={closeConnectModal}
            title="Connect Codex"
            description="Sign in to Codex on your computer. Then paste the sign-in file here."
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
                        onClick={submitAuthFile}
                        loading={connecting}
                        disabledReason={!authFileText.trim() ? 'Paste the contents of auth.json first' : undefined}
                        data-attr="codex-connect-submit"
                    >
                        Connect
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">1. Sign in with your ChatGPT account</h4>
                    <CodeSnippet language={Language.Bash} compact wrap thing="command">
                        {LOGIN_COMMAND}
                    </CodeSnippet>
                    <p className="mb-0 text-xs text-secondary">
                        This uses a separate folder, so your local Codex sign-in keeps working. On a computer without a
                        browser, add <code>--device-auth</code> to the command.
                    </p>
                </div>
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">2. Copy the sign-in file</h4>
                    <CodeSnippet language={Language.Bash} compact wrap thing="command">
                        {COPY_COMMAND}
                    </CodeSnippet>
                </div>
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">3. Paste the file here</h4>
                    <LemonTextArea
                        value={authFileText}
                        onChange={setAuthFileText}
                        placeholder='{ "tokens": { … } }'
                        minRows={4}
                        maxRows={8}
                        className="font-mono text-xs"
                        data-attr="codex-auth-file-input"
                    />
                </div>
                {connectError ? <LemonBanner type="error">{connectError}</LemonBanner> : null}
                <LemonBanner type="info">
                    This file gives access to your ChatGPT account. PostHog stores it encrypted and uses it only for
                    your Codex cloud tasks. You can disconnect at any time.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
