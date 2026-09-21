import '@xterm/xterm/css/xterm.css'

import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconInfo, IconTerminal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonTabs, LemonTag, Popover } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { terminalLogic } from './terminalLogic'
import { TerminalRuntime } from './terminalRuntime'

export const scene: SceneExport = { component: TerminalScene, logic: terminalLogic }

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

export function TerminalScene(): JSX.Element {
    const { status, error, saveError, tab } = useValues(terminalLogic)
    const { start, stop, setTab } = useActions(terminalLogic)
    const container = useRef<HTMLDivElement>(null)
    const terminal = useRef<Terminal | null>(null)
    const runtime = useRef<TerminalRuntime | null>(null)
    const fit = useRef<FitAddon | null>(null)
    const screen = useRef<HTMLDivElement>(null)
    const [hasSelection, setHasSelection] = useState(false)
    const [pasting, setPasting] = useState(false)
    const [clipboardError, setClipboardError] = useState<string | null>(null)
    const [infoOpen, setInfoOpen] = useState(false)

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
        if (!view || !screen.current) {
            return
        }
        view.clear()
        const session = new TerminalRuntime(
            (bytes) => view.write(bytes),
            screen.current,
            (active) => setTab(active ? 'display' : 'terminal')
        )
        runtime.current = session
        fit.current?.fit()
        session.resize(view.cols, view.rows)
        start(session)
        view.focus()
    }

    // The visible tab owns the keyboard, so switching tabs needs no extra click.
    useEffect(() => {
        if (tab === 'display') {
            screen.current?.focus()
        } else {
            terminal.current?.focus()
        }
    }, [tab])

    const active = status !== 'idle' && status !== 'error'
    const notReady = status !== 'ready' ? 'Start the terminal first' : undefined

    return (
        <SceneContent className="h-full min-h-0 flex-1 pb-4">
            <SceneTitleSection name="Terminal" resourceType={{ type: 'terminal', forceIcon: <IconTerminal /> }} />
            <div className="flex shrink-0 items-center gap-2 flex-wrap">
                <LemonButton
                    type={active ? 'secondary' : 'primary'}
                    onClick={active ? stop : startTerminal}
                    data-attr={active ? 'terminal-stop' : 'terminal-start'}
                >
                    {active ? 'Stop' : 'Start Linux'}
                </LemonButton>
                {tab === 'terminal' ? (
                    <>
                        <LemonButton
                            onClick={() =>
                                void copyToClipboard(terminal.current?.getSelection() ?? '', 'terminal selection')
                            }
                            disabledReason={!hasSelection ? 'Select terminal text to copy' : undefined}
                            data-attr="terminal-copy"
                        >
                            Copy selection
                        </LemonButton>
                        <LemonButton
                            onClick={() => void pasteClipboard()}
                            loading={pasting}
                            disabledReason={notReady}
                            data-attr="terminal-paste"
                        >
                            Paste
                        </LemonButton>
                        <LemonMenu
                            items={examples.map(({ title, commands }) => ({
                                title,
                                items: commands.map((command) => ({
                                    label: <code className="whitespace-normal break-words">{command}</code>,
                                    onClick: () => insertCommand(command),
                                })),
                            }))}
                        >
                            <LemonButton
                                type="secondary"
                                aria-label="Examples"
                                tooltip="Insert a command, then press Enter to run it."
                                disabledReason={notReady}
                            >
                                Examples
                            </LemonButton>
                        </LemonMenu>
                    </>
                ) : (
                    <>
                        <LemonButton
                            onClick={() => runtime.current?.fullscreen()}
                            disabledReason={notReady}
                            data-attr="terminal-display-fullscreen"
                        >
                            Full screen
                        </LemonButton>
                        <LemonButton
                            onClick={() => runtime.current?.captureMouse()}
                            disabledReason={notReady}
                            tooltip="Send mouse movement to Linux. Press Esc to release the mouse."
                            data-attr="terminal-display-mouse"
                        >
                            Capture mouse
                        </LemonButton>
                        <LemonButton
                            onClick={() => runtime.current?.interrupt()}
                            disabledReason={notReady}
                            tooltip="Send Ctrl+C to the terminal to stop the running program."
                            data-attr="terminal-display-interrupt"
                        >
                            Interrupt
                        </LemonButton>
                    </>
                )}
                <LemonTag
                    role="status"
                    className="ml-auto"
                    type={status === 'ready' ? 'success' : status === 'error' ? 'danger' : 'default'}
                >
                    {status === 'loading'
                        ? 'Loading project files…'
                        : status === 'booting'
                          ? 'Starting Linux…'
                          : status === 'ready'
                            ? 'Ready'
                            : status === 'error'
                              ? 'Could not start'
                              : 'Stopped'}
                </LemonTag>
                <Popover
                    visible={infoOpen}
                    onClickOutside={() => setInfoOpen(false)}
                    placement="bottom-end"
                    overlay={
                        <div className="flex max-w-80 flex-col items-start gap-3 p-1 text-sm">
                            <LemonTag type="warning">Experiment</LemonTag>
                            <p className="mb-0">
                                Linux in your browser, with your PostHog project mounted at <code>/posthog</code>. The
                                first start downloads Linux and bundled tools (about 15 MB).
                            </p>
                            <p className="mb-0">
                                Commands and file edits can change real data. Local files and unsaved edits disappear
                                when you leave this page.
                            </p>
                            <p className="mb-0">
                                Choose an example to insert it, then press Enter. Tab completes paths. Ctrl+C
                                interrupts. Scroll up for history.
                            </p>
                            <p className="mb-0">
                                Selecting text copies it. Copy/paste with ⌘C/⌘V on macOS or Ctrl+Shift+C/V on Linux and
                                Windows.
                            </p>
                            <p className="mb-0">
                                Graphical programs such as <code>doom</code> open in the Display tab. While that tab is
                                open, your keyboard goes to Linux.
                            </p>
                        </div>
                    }
                >
                    <LemonButton
                        icon={<IconInfo />}
                        aria-label="Terminal information"
                        aria-expanded={infoOpen}
                        active={infoOpen}
                        onClick={() => setInfoOpen(!infoOpen)}
                    />
                </Popover>
            </div>
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
            {clipboardError && <LemonBanner type="error">{clipboardError}</LemonBanner>}
            <LemonTabs
                className="shrink-0"
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    { key: 'terminal', label: 'Terminal' },
                    { key: 'display', label: 'Display' },
                ]}
            />
            {/* Both panes stay laid out: xterm's fit addon and v86's canvas break inside a display: none parent. */}
            <div className="relative min-h-0 min-w-0 flex-1">
                <div
                    aria-label="Linux terminal"
                    data-attr="posthog-terminal"
                    translate="no"
                    className={`absolute inset-0 overflow-hidden rounded border p-3 bg-[var(--color-black)] text-[var(--color-white)] ${
                        tab === 'terminal' ? '' : 'invisible'
                    }`}
                >
                    {/* xterm's fit addon counts padding on its parent as usable space. */}
                    <div ref={container} className="h-full min-w-0 bg-[var(--color-black)]" />
                </div>
                <div
                    ref={screen}
                    tabIndex={0}
                    aria-label="Linux display"
                    data-attr="posthog-terminal-display"
                    translate="no"
                    onFocus={() => runtime.current?.setDisplayInput(true)}
                    onBlur={() => runtime.current?.setDisplayInput(false)}
                    className={`absolute inset-0 flex items-center justify-center overflow-hidden rounded border bg-[var(--color-black)] focus:outline-2 focus:outline-[var(--color-accent)] [&>canvas]:!h-full [&>canvas]:!w-full [&>canvas]:object-contain [&>canvas]:[image-rendering:pixelated] ${
                        tab === 'display' ? '' : 'invisible'
                    }`}
                >
                    <div className="hidden" />
                    <canvas className="block" />
                </div>
            </div>
            {tab === 'display' && (
                <span className="text-secondary shrink-0 text-xs">
                    Your keyboard goes to Linux while the display is selected. Click outside it to release the keyboard.
                </span>
            )}
        </SceneContent>
    )
}
