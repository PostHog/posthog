/**
 * HACK companion to `sessionLogsLogic`. Renders a polled view of a single
 * session's timeline. Will be replaced when the real log surface lands.
 */
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { sessionLogsLogic, type SessionLogEntry } from '../sessionLogsLogic'

export interface SessionLogsPanelProps {
    applicationSlug: string
    sessionId: string
}

export function SessionLogsPanel({ applicationSlug, sessionId }: SessionLogsPanelProps): JSX.Element {
    const logic = sessionLogsLogic({ applicationSlug, sessionId })
    const { entries, loading, error } = useValues(logic)
    const { start, stop, fetchNow } = useActions(logic)
    const scrollRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        start()
        return () => {
            stop()
        }
    }, [applicationSlug, sessionId, start, stop])

    // Auto-scroll to bottom when new entries arrive, but only if the user is
    // already near the bottom (don't yank scroll if they're reading history).
    useEffect(() => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
        if (nearBottom) {
            el.scrollTop = el.scrollHeight
        }
    }, [entries.length])

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 as-mono text-xs">
                    <span
                        style={{
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            background: loading ? 'var(--as-accent)' : 'var(--as-live)',
                            display: 'inline-block',
                            boxShadow: '0 0 6px var(--as-live-glow)',
                        }}
                    />
                    <span style={{ color: 'var(--as-text-muted)' }}>polling · {entries.length} entries</span>
                    {error ? <span style={{ color: 'var(--as-warning)' }}>· {error}</span> : null}
                </div>
                <button
                    className="as-mono text-xs"
                    onClick={() => fetchNow()}
                    style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--as-accent)',
                        cursor: 'pointer',
                        padding: 0,
                    }}
                >
                    ↻ refresh
                </button>
            </div>
            <div
                ref={scrollRef}
                className="as-mono text-xs"
                style={{
                    height: 260,
                    overflowY: 'auto',
                    padding: 10,
                    background: 'var(--as-surface)',
                    border: '1px solid var(--as-border)',
                    borderRadius: 3,
                }}
            >
                {entries.length === 0 ? (
                    <div style={{ color: 'var(--as-text-dim)' }}>
                        // waiting for activity — log buffer is empty (or this session predates log capture)
                    </div>
                ) : (
                    entries.map((entry, i) => <LogLine key={i} entry={entry} />)
                )}
            </div>
        </div>
    )
}

function LogLine({ entry }: { entry: SessionLogEntry }): JSX.Element {
    if (entry.kind === 'log') {
        const color =
            entry.level === 'error'
                ? 'var(--as-error)'
                : entry.level === 'warn'
                  ? 'var(--as-warning)'
                  : entry.level === 'debug'
                    ? 'var(--as-text-dim)'
                    : 'var(--as-text-muted)'
        return (
            <div style={{ color, marginBottom: 2 }}>
                <span style={{ color: 'var(--as-text-dim)' }}>{formatTime(entry.at)}</span>{' '}
                <span style={{ textTransform: 'uppercase' }}>{entry.level}</span> {entry.message}
            </div>
        )
    }
    const type = entry.type
    const fields = entry as Record<string, unknown>
    const accent =
        type === 'tool_call' || type === 'tool_result'
            ? 'var(--as-accent)'
            : type === 'session_failed'
              ? 'var(--as-error)'
              : type === 'session_completed'
                ? 'var(--as-live)'
                : 'var(--as-text-bright)'
    return (
        <div style={{ marginBottom: 2 }}>
            <span style={{ color: 'var(--as-text-dim)' }}>{formatTime(entry.at)}</span>{' '}
            <span style={{ color: accent }}>{type}</span>{' '}
            <span style={{ color: 'var(--as-text-muted)' }}>{summariseEvent(type, fields)}</span>
        </div>
    )
}

function formatTime(iso: string): string {
    try {
        const d = new Date(iso)
        const hh = String(d.getHours()).padStart(2, '0')
        const mm = String(d.getMinutes()).padStart(2, '0')
        const ss = String(d.getSeconds()).padStart(2, '0')
        const ms = String(d.getMilliseconds()).padStart(3, '0')
        return `${hh}:${mm}:${ss}.${ms}`
    } catch {
        return iso
    }
}

function summariseEvent(type: string, fields: Record<string, unknown>): string {
    if (type === 'tool_call') {
        const tool = String(fields.tool ?? '?')
        const args = fields.args
        return args === undefined ? tool : `${tool} ${truncate(JSON.stringify(args), 200)}`
    }
    if (type === 'tool_result') {
        const tool = String(fields.tool ?? '?')
        const ok = fields.ok ? 'ok' : `err=${String(fields.error ?? 'unknown')}`
        return `${tool} → ${ok}`
    }
    if (type === 'message') {
        const role = String(fields.role ?? 'assistant')
        const content = String(fields.content ?? '')
        return `${role}: ${truncate(content, 300)}`
    }
    if (type === 'session_failed') {
        return String(fields.error ?? 'unknown')
    }
    if (type === 'session_completed') {
        const output = fields.output
        return output === undefined ? '' : truncate(JSON.stringify(output), 200)
    }
    return ''
}

function truncate(s: string, n: number): string {
    return s.length > n ? s.slice(0, n) + '…' : s
}
