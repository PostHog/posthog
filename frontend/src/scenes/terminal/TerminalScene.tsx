import '@xterm/xterm/css/xterm.css'

import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconEllipsis, IconTerminal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { terminalLogic } from './terminalLogic'
import { TerminalRuntime } from './terminalRuntime'

export const scene: SceneExport = { component: TerminalScene, logic: terminalLogic }

const examples = ['ls --color=auto', "find /posthog/files -name '*.md'", 'cat /posthog/README.txt', 'ph help']
const moreExamples = [
    { title: 'Explore files', commands: ['ls -lh /posthog/api', 'du -ah /posthog/files', 'pwd', 'busybox'] },
    { title: 'PostHog tools', commands: ['ph tools', 'ph tools notebook', 'ph help notebooks-retrieve', 'ph refresh'] },
    {
        title: 'Edit and organize',
        commands: [
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

export function TerminalScene(): JSX.Element {
    const { status, error, saveError } = useValues(terminalLogic)
    const { start, stop } = useActions(terminalLogic)
    const container = useRef<HTMLDivElement>(null)
    const terminal = useRef<Terminal | null>(null)
    const runtime = useRef<TerminalRuntime | null>(null)
    const fit = useRef<FitAddon | null>(null)
    const [hasSelection, setHasSelection] = useState(false)
    const [pasting, setPasting] = useState(false)
    const [clipboardError, setClipboardError] = useState<string | null>(null)

    function insertCommand(command: string): void {
        terminal.current?.paste(command)
        terminal.current?.focus()
    }

    async function pasteClipboard(): Promise<void> {
        setPasting(true)
        setClipboardError(null)
        try {
            const text = await navigator.clipboard.readText()
            terminal.current?.paste(text)
            terminal.current?.focus()
        } catch {
            setClipboardError('Could not read the clipboard. Focus the terminal and use your browser’s paste shortcut.')
        } finally {
            setPasting(false)
        }
    }

    useEffect(() => {
        if (!container.current) {
            return
        }
        const styles = getComputedStyle(container.current)
        const view = new Terminal({
            cursorBlink: true,
            scrollback: 10_000,
            fontSize: 14,
            fontFamily: 'monospace',
            screenReaderMode: true,
            rightClickSelectsWord: true,
            theme: { background: styles.backgroundColor, foreground: styles.color, cursor: styles.color },
        })
        const fitAddon = new FitAddon()
        view.loadAddon(fitAddon)
        view.open(container.current)
        terminal.current = view
        fit.current = fitAddon
        view.attachCustomKeyEventHandler((event) => {
            const key = event.key.toLowerCase()
            const shortcut = event.metaKey || (event.ctrlKey && event.shiftKey)
            if (shortcut && (key === 'c' || key === 'v')) {
                event.stopPropagation()
                if (key === 'c' || !event.metaKey) {
                    event.preventDefault()
                    if (event.type === 'keydown') {
                        if (key === 'c' && view.hasSelection()) {
                            void copyToClipboard(view.getSelection(), 'terminal selection')
                        } else if (key === 'v') {
                            void pasteClipboard()
                        }
                    }
                }
                return false
            }
            return true
        })
        const selection = view.onSelectionChange(() => {
            setHasSelection(view.hasSelection())
            if (view.hasSelection()) {
                void copyToClipboard(view.getSelection(), 'terminal selection', { silent: true })
            }
        })
        const input = view.onData((data) => runtime.current?.write(data))
        const resize = view.onResize(({ cols, rows }) => runtime.current?.resize(cols, rows))
        const observer = new ResizeObserver(() => fitAddon.fit())
        observer.observe(container.current)
        fitAddon.fit()
        view.writeln('Start Linux to mount your PostHog project at /posthog.')
        return () => {
            stop()
            observer.disconnect()
            input.dispose()
            resize.dispose()
            selection.dispose()
            view.dispose()
            terminal.current = null
        }
    }, [stop])

    function startTerminal(): void {
        const view = terminal.current
        if (!view) {
            return
        }
        view.clear()
        const session = new TerminalRuntime((bytes) => view.write(bytes))
        runtime.current = session
        fit.current?.fit()
        session.resize(view.cols, view.rows)
        start(session)
        view.focus()
    }

    const active = status !== 'idle' && status !== 'error'
    const starting = status === 'loading' || status === 'booting'

    return (
        <SceneContent>
            <SceneTitleSection name="Terminal" resourceType={{ type: 'terminal', forceIcon: <IconTerminal /> }} />
            <div className="flex items-center gap-2 flex-wrap">
                <LemonTag type="warning">Experiment</LemonTag>
                <span className="text-secondary">
                    Linux in your browser, with your PostHog project mounted at /posthog.
                </span>
            </div>
            <LemonBanner type="info">
                Commands and notebook edits can change real data. Local files and unsaved edits disappear when you leave
                this page. The first start downloads Linux and jq (about 8 MB).
            </LemonBanner>
            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    type="primary"
                    onClick={startTerminal}
                    loading={starting}
                    disabledReason={active ? 'The terminal is already running' : undefined}
                    data-attr="terminal-start"
                >
                    Start Linux
                </LemonButton>
                <LemonButton
                    onClick={stop}
                    disabledReason={status === 'idle' ? 'Start the terminal first' : undefined}
                    data-attr="terminal-stop"
                >
                    Stop
                </LemonButton>
                <LemonButton
                    onClick={() => void copyToClipboard(terminal.current?.getSelection() ?? '', 'terminal selection')}
                    disabledReason={!hasSelection ? 'Select terminal text to copy' : undefined}
                    data-attr="terminal-copy"
                >
                    Copy selection
                </LemonButton>
                <LemonButton
                    onClick={() => void pasteClipboard()}
                    loading={pasting}
                    disabledReason={status !== 'ready' ? 'Start the terminal first' : undefined}
                    data-attr="terminal-paste"
                >
                    Paste
                </LemonButton>
                <span role="status" className="text-secondary">
                    {status === 'loading'
                        ? 'Loading project files…'
                        : status === 'booting'
                          ? 'Starting Linux…'
                          : status === 'ready'
                            ? 'Ready'
                            : status === 'error'
                              ? 'Could not start'
                              : 'Stopped'}
                </span>
            </div>
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
            {clipboardError && <LemonBanner type="error">{clipboardError}</LemonBanner>}
            <div
                ref={container}
                aria-label="Linux terminal"
                data-attr="posthog-terminal"
                translate="no"
                className="h-128 min-w-0 overflow-hidden rounded border p-3 bg-[var(--color-black)] text-[var(--color-white)]"
            />
            <div className="flex items-center gap-1 flex-wrap" data-attr="terminal-examples">
                <span className="text-secondary text-sm">Try</span>
                {examples.map((command) => (
                    <LemonButton
                        key={command}
                        size="xsmall"
                        type="secondary"
                        tooltip="Insert command. Press Enter to run."
                        aria-label={command}
                        disabledReason={status !== 'ready' ? 'Start the terminal first' : undefined}
                        onClick={() => insertCommand(command)}
                    >
                        <code>{command}</code>
                    </LemonButton>
                ))}
                <LemonMenu
                    items={moreExamples.map(({ title, commands }) => ({
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
                        icon={<IconEllipsis />}
                        aria-label="More terminal examples"
                        disabledReason={status !== 'ready' ? 'Start the terminal first' : undefined}
                    />
                </LemonMenu>
            </div>
            <p className="text-secondary text-sm mb-0">
                Click an example to insert it, then press Enter. Selecting text copies it. Tab completes paths. Ctrl+C
                interrupts. Copy/paste with ⌘C/⌘V on macOS or Ctrl+Shift+C/V on Linux and Windows. Scroll up for
                history.
            </p>
        </SceneContent>
    )
}
