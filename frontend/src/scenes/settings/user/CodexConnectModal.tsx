import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { platformCommandControlKey } from 'lib/utils/dom'

import { CODEX_LOGIN_PLATFORM_OPTIONS, codexLoginCommand } from './codexLoginCommands'
import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

const PLATFORM_HINTS = {
    macos: 'Run it in Terminal.',
    linux: 'Run it in a terminal. It needs wl-clipboard, xclip, or xsel to copy to the clipboard.',
    windows: 'Run it in PowerShell.',
}

export const SETTINGS_CODEX_CONNECT_OPENER = 'settings'

export interface CodexConnectModalProps {
    /** Several surfaces can show the dialog at once. Each opens only for the opener that asked for it. */
    opener: string
}

export function CodexConnectModal({ opener }: CodexConnectModalProps): JSX.Element {
    const { connectModalOpener, authFileText, connectError, connecting, loginPlatform } =
        useValues(personalCodexIntegrationLogic)
    const { closeConnectModal, setLoginPlatform, commandCopied, pasteAuthFile, pasteFromClipboard, submitAuthFile } =
        useActions(personalCodexIntegrationLogic)
    const pasted = authFileText.length > 0

    return (
        <LemonModal
            isOpen={connectModalOpener === opener}
            onClose={closeConnectModal}
            closable={!connecting}
            title="Connect Codex"
            description="Sign in to ChatGPT with a device code in your terminal. Then paste the sign-in here."
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
                        disabledReason={!pasted ? 'Paste the sign-in first' : undefined}
                        data-attr="codex-connect-submit"
                    >
                        Connect
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <h4 className="mb-0">1. Run this command</h4>
                        <LemonSegmentedButton
                            size="small"
                            value={loginPlatform}
                            onChange={setLoginPlatform}
                            options={CODEX_LOGIN_PLATFORM_OPTIONS}
                            data-attr="codex-login-platform"
                        />
                    </div>
                    <CodeSnippet
                        language={loginPlatform === 'windows' ? Language.Text : Language.Bash}
                        compact
                        wrap
                        thing="command"
                        onCopy={commandCopied}
                    >
                        {codexLoginCommand(loginPlatform)}
                    </CodeSnippet>
                    <p className="mb-0 text-xs text-secondary">
                        <span>{PLATFORM_HINTS[loginPlatform]}</span> Open the link that it shows, sign in, and enter the
                        one-time code. The command copies your sign-in to the clipboard and deletes its temporary
                        folder, so nothing stays on your computer.
                    </p>
                    <p className="mb-0 text-xs text-secondary">
                        You need the{' '}
                        <Link to="https://developers.openai.com/codex/cli" target="_blank">
                            Codex CLI
                        </Link>
                        . Install it with <code>npm install -g @openai/codex</code>.
                    </p>
                    <p className="mb-0 text-xs text-secondary">
                        Turn on device code login in your ChatGPT security settings first. In a ChatGPT workspace, an
                        admin turns it on in the workspace permissions.
                    </p>
                </div>
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">2. Paste the sign-in</h4>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonInput
                            className="min-w-48 flex-1"
                            value=""
                            onChange={() => undefined}
                            onPaste={(event) => {
                                event.preventDefault()
                                pasteAuthFile(event.clipboardData.getData('text'))
                            }}
                            placeholder={
                                pasted ? 'Sign-in received' : `Click here and press ${platformCommandControlKey('V')}`
                            }
                            suffix={pasted ? <IconCheck className="text-success" /> : undefined}
                            autoComplete="off"
                            spellCheck={false}
                            disabled={connecting}
                            data-attr="codex-auth-file-input"
                        />
                        <LemonButton
                            type="secondary"
                            onClick={pasteFromClipboard}
                            disabledReason={connecting ? 'Connecting…' : undefined}
                            data-attr="codex-paste-from-clipboard"
                        >
                            Paste from clipboard
                        </LemonButton>
                    </div>
                </div>
                {connectError ? <LemonBanner type="error">{connectError}</LemonBanner> : null}
                <LemonBanner type="info">
                    PostHog never shows your sign-in and tries to clear your clipboard after you paste. It stores the
                    sign-in encrypted and uses it only for your Codex cloud tasks. You can disconnect at any time.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
