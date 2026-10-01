import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

const LOGIN_COMMAND = 'mkdir -p ~/.codex-posthog && CODEX_HOME=~/.codex-posthog codex login --device-auth'
const COPY_COMMAND = 'cat ~/.codex-posthog/auth.json'

export function CodexConnectModal(): JSX.Element {
    const { connectModalOpen, authFileText, connectError, connecting } = useValues(personalCodexIntegrationLogic)
    const { closeConnectModal, setAuthFileText, submitAuthFile } = useActions(personalCodexIntegrationLogic)

    return (
        <LemonModal
            isOpen={connectModalOpen}
            onClose={closeConnectModal}
            title="Connect Codex"
            description="Sign in to Codex with a device code on your computer. Then paste the sign-in file here."
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
                    <h4 className="mb-0">1. Sign in with a device code</h4>
                    <CodeSnippet language={Language.Bash} compact wrap thing="command">
                        {LOGIN_COMMAND}
                    </CodeSnippet>
                    <p className="mb-0 text-xs text-secondary">
                        Turn on device code login in your ChatGPT security settings first. In a ChatGPT workspace, an
                        admin turns it on in the workspace permissions.
                    </p>
                    <p className="mb-0 text-xs text-secondary">
                        Open the link that the command shows, sign in, and enter the one-time code. The command uses a
                        separate folder, so your local Codex sign-in keeps working.
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
