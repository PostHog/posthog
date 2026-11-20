import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCollapse, LemonModal, Link, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

export const SETTINGS_CODEX_CONNECT_OPENER = 'settings'

export interface CodexConnectModalProps {
    opener: string
}

export function CodexConnectModal({ opener }: CodexConnectModalProps): JSX.Element {
    const { connectModalOpener, login, connectError, cancelError, canceling } = useValues(personalCodexIntegrationLogic)
    const { closeConnectModal, startDeviceLogin } = useActions(personalCodexIntegrationLogic)

    return (
        <LemonModal
            isOpen={connectModalOpener === opener}
            onClose={closeConnectModal}
            title="Connect Codex"
            width={480}
            description="Use your ChatGPT plan for Codex cloud tasks."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeConnectModal} loading={canceling}>
                        {cancelError ? 'Retry cancellation' : 'Cancel'}
                    </LemonButton>
                    {!cancelError &&
                        !canceling &&
                        (connectError ? (
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
                        ) : null)}
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {cancelError || connectError ? (
                    <div role="alert">
                        <LemonBanner type={login?.status === 'expired' ? 'warning' : 'error'}>
                            {cancelError || connectError}
                        </LemonBanner>
                    </div>
                ) : login?.user_code ? (
                    <>
                        <p className="mb-0">Copy this code, then enter it in ChatGPT.</p>
                        <div className="ph-no-capture" data-private translate="no">
                            <CodeSnippet language={Language.Text} thing="device code">
                                {login.user_code}
                            </CodeSnippet>
                        </div>
                        <p role="status" className="mb-0 text-sm text-secondary">
                            Waiting for approval in ChatGPT...
                        </p>
                    </>
                ) : (
                    <div role="status" className="flex items-center gap-2 py-4">
                        <Spinner />
                        <span>
                            {login?.status === 'connected' ? 'Connecting your account...' : 'Getting a device code...'}
                        </span>
                    </div>
                )}
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'device-login-help',
                            header: 'Device login help',
                            content: (
                                <p className="mb-0 text-sm text-secondary">
                                    Enable device code login in your{' '}
                                    <Link to="https://chatgpt.com/#settings/Security" target="_blank">
                                        ChatGPT security settings
                                    </Link>
                                    . In a ChatGPT workspace, ask an administrator to enable it.
                                </p>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
