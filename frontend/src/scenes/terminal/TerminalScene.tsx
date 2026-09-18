import '@xterm/xterm/css/xterm.css'

import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconTerminal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { terminalLogic } from './terminalLogic'
import { TerminalRuntime } from './terminalRuntime'

export const scene: SceneExport = { component: TerminalScene, logic: terminalLogic }

export function TerminalScene(): JSX.Element {
    const { status, error, saveError } = useValues(terminalLogic)
    const { start, stop } = useActions(terminalLogic)
    const container = useRef<HTMLDivElement>(null)
    const terminal = useRef<Terminal | null>(null)
    const runtime = useRef<TerminalRuntime | null>(null)
    const fit = useRef<FitAddon | null>(null)

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
            theme: { background: styles.backgroundColor, foreground: styles.color, cursor: styles.color },
        })
        const fitAddon = new FitAddon()
        view.loadAddon(fitAddon)
        view.open(container.current)
        terminal.current = view
        fit.current = fitAddon
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
                Saving a markdown notebook writes to PostHog. Local files and unsaved edits disappear when you leave
                this page. The first start downloads a Linux image (about 10 MB) from the v86 project.
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
            <div
                ref={container}
                aria-label="Linux terminal"
                data-attr="posthog-terminal"
                translate="no"
                className="h-128 min-w-0 overflow-hidden rounded border p-3 bg-surface-primary text-primary"
            />
            <p className="text-secondary text-sm mb-0">
                Try <code>ls --color=auto</code>, <code>find /posthog/files -name '*.md'</code>, or{' '}
                <code>cat /posthog/README.txt</code>. Tab completes paths. Ctrl+C interrupts. Scroll up for history.
            </p>
        </SceneContent>
    )
}
