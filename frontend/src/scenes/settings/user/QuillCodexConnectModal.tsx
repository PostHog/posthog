import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Heading,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Item,
    ItemContent,
    ItemDescription,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { platformCommandControlKey } from 'lib/utils/dom'

import { CodexConnectModalProps, PLATFORM_HINTS } from './CodexConnectModal'
import { CODEX_LOGIN_PLATFORM_OPTIONS, CodexLoginPlatform, codexLoginCommand } from './codexLoginCommands'
import { personalCodexIntegrationLogic } from './personalCodexIntegrationLogic'

export function QuillCodexConnectModal({ opener }: CodexConnectModalProps): JSX.Element {
    const { connectModalOpener, authFileText, connectError, connecting, loginPlatform } =
        useValues(personalCodexIntegrationLogic)
    const { closeConnectModal, setLoginPlatform, commandCopied, pasteAuthFile, pasteFromClipboard, submitAuthFile } =
        useActions(personalCodexIntegrationLogic)
    const pasted = authFileText.length > 0

    return (
        <Dialog
            open={connectModalOpener === opener}
            onOpenChange={(open: boolean) => {
                if (!open && !connecting) {
                    closeConnectModal()
                }
            }}
        >
            <DialogContent showCloseButton={!connecting}>
                <DialogHeader>
                    <DialogTitle>Connect Codex</DialogTitle>
                    <DialogDescription>
                        Sign in to ChatGPT with a device code in your terminal. Then paste the sign-in here.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-col gap-2">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    1. Run this command
                                </Heading>
                                <ToggleGroup
                                    className="flex-wrap"
                                    value={[loginPlatform]}
                                    onValueChange={(next: string[]) => {
                                        if (next[0]) {
                                            setLoginPlatform(next[0] as CodexLoginPlatform)
                                        }
                                    }}
                                    data-attr="codex-login-platform"
                                >
                                    {CODEX_LOGIN_PLATFORM_OPTIONS.map((option) => (
                                        <ToggleGroupItem key={option.value} value={option.value}>
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
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
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                <span>{PLATFORM_HINTS[loginPlatform]}</span> Open the link that it shows, sign in, and
                                enter the one-time code. The command copies your sign-in to the clipboard and deletes
                                its temporary folder, so nothing stays on your computer.
                            </Text>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                You need the{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive to="https://developers.openai.com/codex/cli" target="_blank" />
                                    }
                                >
                                    Codex CLI
                                </Button>
                                . Install it with <code>npm install -g @openai/codex</code>.
                            </Text>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Turn on device code login in your ChatGPT security settings first. In a ChatGPT
                                workspace, an admin turns it on in the workspace permissions.
                            </Text>
                        </div>
                        <div className="flex flex-col gap-2">
                            <Heading size="sm" render={<h3 className="m-0" />}>
                                2. Paste the sign-in
                            </Heading>
                            <div className="flex flex-wrap items-center gap-2">
                                <InputGroup className="min-w-48 flex-1">
                                    <InputGroupInput
                                        value=""
                                        onChange={() => undefined}
                                        onPaste={(event) => {
                                            event.preventDefault()
                                            pasteAuthFile(event.clipboardData.getData('text'))
                                        }}
                                        placeholder={
                                            pasted
                                                ? 'Sign-in received'
                                                : `Click here and press ${platformCommandControlKey('V')}`
                                        }
                                        aria-label="Paste the sign-in"
                                        autoComplete="off"
                                        spellCheck={false}
                                        disabled={connecting}
                                        data-attr="codex-auth-file-input"
                                    />
                                    {pasted ? (
                                        <InputGroupAddon align="inline-end">
                                            <IconCheck className="text-success-foreground" />
                                        </InputGroupAddon>
                                    ) : null}
                                </InputGroup>
                                <Button
                                    variant="outline"
                                    onClick={pasteFromClipboard}
                                    disabledReason={connecting ? 'Connecting…' : undefined}
                                    data-attr="codex-paste-from-clipboard"
                                >
                                    Paste from clipboard
                                </Button>
                            </div>
                        </div>
                        {connectError ? (
                            <Item tone="destructive" size="sm">
                                <ItemContent>
                                    <ItemDescription>{connectError}</ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : null}
                        <Item tone="info" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    PostHog never shows your sign-in and tries to clear your clipboard after you paste.
                                    It stores the sign-in encrypted and uses it only for your Codex cloud tasks. You can
                                    disconnect at any time.
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeConnectModal}
                        disabledReason={connecting ? 'Connecting…' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitAuthFile}
                        loading={connecting}
                        disabledReason={!pasted ? 'Paste the sign-in first' : undefined}
                        data-attr="codex-connect-submit"
                    >
                        Connect
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
