import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Link, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

export const SETTINGS_CODEX_CONNECT_OPENER = 'settings'

export interface CodexConnectModalProps {
    opener: string
}

export function CodexConnectModal({ opener }: CodexConnectModalProps): JSX.Element {
    const { connectModalOpener, login, connectError } = useValues(personalCodexIntegrationLogic)
    const { closeConnectModal, startDeviceLogin } = useActions(personalCodexIntegrationLogic)

    return (
        <LemonModal
            isOpen={connectModalOpener === opener}
            onClose={closeConnectModal}
            title="Connect Codex"
            width={560}
            description="Approve the device code in ChatGPT to use your plan for cloud tasks."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeConnectModal}>
                        Cancel
                    </LemonButton>
                    {connectError ? (
                        <LemonButton type="primary" onClick={startDeviceLogin} data-attr="codex-device-login-retry">
                            Try again
                        </LemonButton>
                    ) : login?.user_code ? (
                        <LemonButton
                            type="primary"
                            to="https://auth.openai.com/codex/device"
                            targetBlank
                            data-attr="codex-device-login-open"
                        >
                            Open ChatGPT
                        </LemonButton>
                    ) : null}
                </>
            }
        >
            <div className="space-y-4">
                {connectError ? (
                    <LemonBanner type="error">{connectError}</LemonBanner>
                ) : login?.user_code ? (
                    <>
                        <p>Enter this code on the ChatGPT device login page:</p>
                        <div className="ph-no-capture" data-private>
                            <CodeSnippet language={Language.Text}>{login.user_code}</CodeSnippet>
                        </div>
                        <p className="text-secondary">Waiting for approval. This window updates when you finish.</p>
                    </>
                ) : (
                    <div className="flex items-center gap-2">
                        <Spinner />
                        Starting the ChatGPT login...
                    </div>
                )}
                <p className="text-secondary">
                    Turn on device code login in your{' '}
                    <Link to="https://chatgpt.com/#settings/Security" target="_blank">
                        ChatGPT security settings
                    </Link>{' '}
                    first. In a ChatGPT workspace, an administrator must enable it.
                </p>
            </div>
        </LemonModal>
    )
}
