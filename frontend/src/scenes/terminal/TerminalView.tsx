import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCopy, IconInfo, IconStopFilled, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonSelect, LemonTag, Popover } from '@posthog/lemon-ui'

import { IconClipboardEdit } from 'lib/lemon-ui/icons'

import type { TerminalSandboxSizeEnumApi } from '~/generated/core/api.schemas'

import { TerminalEnvironment, terminalLogic } from './terminalLogic'

const sandboxSizes: { value: TerminalSandboxSizeEnumApi; label: string }[] = [
    { value: 'small', label: 'Small · 1 CPU · 2 GB RAM' },
    { value: 'balanced', label: 'Balanced · 4 CPUs · 8 GB RAM' },
    { value: 'large', label: 'Large · 8 CPUs · 16 GB RAM' },
    { value: 'high_memory', label: 'High memory · 8 CPUs · 32 GB RAM' },
]

const examples = [
    {
        title: 'Get started',
        commands: ['ls --color=auto', "find /posthog/files -name '*.md'", 'cat /posthog/README.txt', 'ph help'],
    },
    {
        title: 'Explore files',
        commands: [
            'mc',
            'tree -C -L 3 /posthog/files',
            'ncdu -r /posthog/files',
            'ls -lh /posthog/api',
            'pwd',
            'busybox',
        ],
    },
    { title: 'Optional tools', commands: ['node --version', 'pi --help', 'nyancat', 'doom'] },
    { title: 'PostHog tools', commands: ['ph tools', 'ph tools notebook', 'ph help notebooks-retrieve', 'ph refresh'] },
    {
        title: 'Edit and organize',
        commands: [
            'nano Unfiled/Notebooks/Foobar.md',
            "find /posthog/files -name '*.json'",
            'vi Unfiled/Notebooks/Foobar.md',
            'mkdir -p Research/Archive',
            'mv Unfiled/Notebooks/Foobar.md Research/Archive/',
        ],
    },
    {
        title: 'Read and filter',
        commands: [
            'ph notebooks-list --limit 10 | jq .',
            "grep -r -n 'revenue' /posthog/files",
            "find /posthog/files -name '*.md' | wc -l",
            'jq -n \'{hello: "PostHog"}\'',
            'less /posthog/README.txt',
            'ls -la /tmp',
        ],
    },
]

export function TerminalView({
    active: visible = true,
    onClose,
}: {
    active?: boolean
    onClose?: () => void
}): JSX.Element {
    const { status, error, saveError, hasSelection, pasting, clipboardError, environment, sandboxSize } =
        useValues(terminalLogic)
    const { start, stop, attach, detach, insertCommand, copy, paste, setEnvironment, setSandboxSize } =
        useActions(terminalLogic)
    const container = useRef<HTMLDivElement>(null)
    const [infoOpen, setInfoOpen] = useState(false)
    const [sizeOpen, setSizeOpen] = useState(false)
    useEffect(() => {
        const host = container.current
        if (!host || !visible) {
            return
        }
        attach(host)
        return () => detach(host)
    }, [attach, detach, visible])

    const active = status !== 'idle' && (status !== 'error' || environment === 'modal')
    const starting = status === 'loading' || status === 'booting'

    return (
        <div className="h-full min-h-0 flex flex-col gap-1">
            <div className="flex shrink-0 items-center gap-1 flex-wrap px-1">
                <LemonSelect
                    size="xsmall"
                    value={environment}
                    onChange={(value) => setEnvironment(value as TerminalEnvironment)}
                    disabledReason={active ? 'Stop the terminal to change environments' : undefined}
                    aria-label="Environment"
                    data-attr="terminal-environment"
                    className="min-w-0 max-w-full"
                    truncateText={{ maxWidthClass: 'max-w-full' }}
                    options={[
                        {
                            title: 'Environment',
                            options: [
                                {
                                    value: 'posthog-linux-wasm',
                                    label: 'PostHog Linux WASM (in-browser, experimental)',
                                },
                                { value: 'modal', label: 'Modal sandbox (cloud, experimental)' },
                            ],
                        },
                    ]}
                />
                {environment === 'modal' && (
                    <Popover
                        visible={sizeOpen}
                        onClickOutside={() => setSizeOpen(false)}
                        placement="bottom-start"
                        overlay={
                            <div className="flex max-w-80 flex-col gap-2 p-1">
                                <span className="font-semibold">Sandbox size</span>
                                <LemonSelect
                                    size="small"
                                    value={sandboxSize}
                                    aria-label="Sandbox size"
                                    data-attr="terminal-sandbox-size"
                                    options={sandboxSizes}
                                    disabledReason={active ? 'Stop the sandbox to change its size' : undefined}
                                    onChange={(value) => setSandboxSize(value)}
                                />
                                <span className="text-xs text-secondary">
                                    New sandboxes use this size. Sandboxes expire after one hour.
                                </span>
                            </div>
                        }
                    >
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => setSizeOpen(!sizeOpen)}
                            aria-expanded={sizeOpen}
                            data-attr="terminal-sandbox-settings"
                        >
                            {sandboxSizes.find(({ value }) => value === sandboxSize)?.label}
                        </LemonButton>
                    </Popover>
                )}
                <LemonButton
                    size="xsmall"
                    type="primary"
                    onClick={start}
                    loading={starting}
                    disabledReason={active ? 'The terminal is already running' : undefined}
                    data-attr="terminal-start"
                >
                    {environment === 'modal' ? 'Start sandbox' : 'Start Linux'}
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    icon={<IconStopFilled />}
                    aria-label="Stop"
                    tooltip="Stop"
                    onClick={() => stop()}
                    loading={status === 'stopping'}
                    disabledReason={
                        status === 'idle'
                            ? 'Start the terminal first'
                            : status === 'stopping'
                              ? 'Stopping the sandbox'
                              : undefined
                    }
                    data-attr="terminal-stop"
                />
                <LemonButton
                    size="xsmall"
                    icon={<IconCopy />}
                    aria-label="Copy"
                    tooltip="Copy"
                    onClick={copy}
                    disabledReason={!hasSelection ? 'Select terminal text to copy' : undefined}
                    data-attr="terminal-copy"
                />
                <LemonButton
                    size="xsmall"
                    icon={<IconClipboardEdit />}
                    aria-label="Paste"
                    tooltip="Paste"
                    onClick={paste}
                    loading={pasting}
                    disabledReason={status !== 'ready' ? 'Start the terminal first' : undefined}
                    data-attr="terminal-paste"
                />
                <LemonMenu
                    items={(environment === 'modal'
                        ? [
                              {
                                  title: 'Sandbox tools',
                                  commands: ['python --version', 'node --version', 'pip list', 'pwd', 'ls -la', 'htop'],
                              },
                          ]
                        : examples
                    ).map(({ title, commands }) => ({
                        title,
                        items: commands.map((command) => ({
                            label: <code className="whitespace-normal break-words">{command}</code>,
                            onClick: () => insertCommand(command),
                        })),
                    }))}
                >
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        aria-label="Examples"
                        tooltip="Insert a command, then press Enter to run it."
                        disabledReason={status !== 'ready' ? 'Start the terminal first' : undefined}
                    >
                        Examples
                    </LemonButton>
                </LemonMenu>
                <span role="status" className="text-secondary ml-auto text-xs">
                    {status === 'stopping'
                        ? 'Stopping sandbox…'
                        : status === 'loading'
                          ? 'Starting terminal…'
                          : status === 'booting'
                            ? 'Starting Linux…'
                            : status === 'ready'
                              ? 'Ready'
                              : status === 'error'
                                ? 'Could not start'
                                : 'Stopped'}
                </span>
                <Popover
                    visible={infoOpen}
                    onClickOutside={() => setInfoOpen(false)}
                    placement="bottom-end"
                    overlay={
                        <div className="flex max-w-80 flex-col items-start gap-3 p-1 text-sm">
                            <LemonTag type="warning">Experiment</LemonTag>
                            <p className="mb-0">
                                {environment === 'modal' ? (
                                    <>
                                        A cloud Linux sandbox with the same Python and Node.js tools as notebooks. The
                                        sandbox has its own filesystem; your PostHog project is not mounted.
                                    </>
                                ) : (
                                    <>
                                        Linux in your browser, with your PostHog project mounted at{' '}
                                        <code>/posthog</code>. The first start downloads Linux and bundled tools.
                                    </>
                                )}
                            </p>
                            <p className="mb-0">
                                {environment === 'modal'
                                    ? 'Stop destroys the sandbox and its files. Sandboxes expire after one hour, including when you close PostHog.'
                                    : 'Commands and file edits can change real data. Local files and unsaved edits disappear when you reload PostHog or stop Linux.'}
                            </p>
                            <p className="mb-0">
                                Choose an example to insert it, then press Enter. Tab completes commands and paths.
                                Ctrl+C interrupts. Scroll up for history.
                            </p>
                            <p className="mb-0">
                                Selecting text copies it automatically. In apps that capture the mouse, such as mc, hold
                                Option on macOS or Shift on Linux and Windows while selecting. Copy/paste with ⌘C/⌘V on
                                macOS or Ctrl+Shift+C/V on Linux and Windows.
                            </p>
                        </div>
                    }
                >
                    <LemonButton
                        size="xsmall"
                        icon={<IconInfo />}
                        aria-label="Terminal information"
                        aria-expanded={infoOpen}
                        active={infoOpen}
                        onClick={() => setInfoOpen(!infoOpen)}
                    />
                </Popover>
                {onClose && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        aria-label="Hide terminal"
                        tooltip="Hide terminal"
                        onClick={onClose}
                    />
                )}
            </div>
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
            {clipboardError && <LemonBanner type="error">{clipboardError}</LemonBanner>}
            <div
                aria-label="Linux terminal"
                data-attr="posthog-terminal"
                translate="no"
                className="min-h-0 min-w-0 flex-1 overflow-hidden px-1 pb-1 bg-[var(--color-black)] text-[var(--color-white)]"
            >
                {/* xterm's fit addon counts padding on its parent as usable space. */}
                <div ref={container} className="h-full min-w-0 bg-[var(--color-black)]" />
            </div>
        </div>
    )
}
