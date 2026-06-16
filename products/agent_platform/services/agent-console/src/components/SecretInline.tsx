/**
 * `<SecretInline />` — chat-rendered editor for the `set_secret` client
 * tool. Mounted next to the matching `tool_call` part by the agent-chat
 * `PartRenderer` when the concierge invokes `set_secret({ ... })`.
 *
 * The form is intentionally smaller than `<SecretEditDialog>`: one
 * password field, a save button, and a tiny status footer. No "current
 * is set / not set" pre-check — the agent decides that before invoking
 * this tool, and the args carry whether this is a set or a rotate.
 *
 * Props are deliberately split from the side-effect (`onSetSecret`) so
 * the story can swap a fake setter in. The `useRealRunner` wires
 * `onSetSecret` to `setEnvKey()` from apiClient.
 *
 * Resolution model:
 *   - On successful save → calls `onResolve({ ok: true, key, action: 'set' })`
 *     which the agent receives as the tool's return value.
 *   - On a 4xx/5xx from the setter → calls `onReject(message)`; the
 *     agent receives `{ error: "<message>" }`. The agent can decide to
 *     surface the error to the user or retry.
 *   - The user can also Cancel; we reject with `user_cancelled` so the
 *     agent knows the call was abandoned rather than failed.
 */

'use client'

import { useState } from 'react'

import { Button, Input, Label } from '@posthog/quill'

export interface SecretInlineArgs {
    /**
     * The agent the secret lands on. Surfaced in the form so the user
     * always knows which app they're configuring — particularly
     * important when the concierge is operating on an agent other
     * than the one currently in view.
     */
    agentSlug: string
    /** The env variable name to set, e.g. `ANTHROPIC_KEY`. */
    secret: string
    /**
     * Whether the agent is creating the value for the first time or
     * rotating an existing one. Drives copy + button label.
     */
    mode?: 'set' | 'rotate'
    /** Optional human-readable hint shown above the input. */
    purpose?: string
}

export interface SecretInlineProps extends SecretInlineArgs {
    /** Persist the value. Resolves on 2xx, rejects on anything else. */
    onSetSecret: (key: string, value: string) => Promise<void>
    /** Resolve the agent's tool call with a success body. */
    onResolve: (body: { key: string; action: 'set' }) => void
    /** Reject the agent's tool call. The string flows back as `{ error }`. */
    onReject: (reason: string) => void
}

export function SecretInline({
    agentSlug,
    secret,
    mode = 'set',
    purpose,
    onSetSecret,
    onResolve,
    onReject,
}: SecretInlineProps): React.ReactElement {
    const [value, setValue] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [done, setDone] = useState(false)

    const submit = async (): Promise<void> => {
        if (!value || submitting || done) {
            return
        }
        setSubmitting(true)
        setError(null)
        try {
            await onSetSecret(secret, value)
            setDone(true)
            onResolve({ key: secret, action: 'set' })
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err)
            setError(msg)
        } finally {
            setSubmitting(false)
        }
    }

    if (done) {
        return (
            <div className="flex items-center gap-2 text-xs text-success-foreground">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
                Secret <code className="font-mono">{secret}</code> saved.
            </div>
        )
    }

    return (
        <form
            onSubmit={(e) => {
                e.preventDefault()
                void submit()
            }}
            className="space-y-2"
            data-slot="secret-inline"
        >
            <div className="flex items-center justify-between gap-2">
                <Label htmlFor={`secret-inline-${secret}`} className="text-[0.6875rem] font-medium">
                    {mode === 'rotate' ? 'Rotate' : 'Set'} <code className="font-mono">{secret}</code>
                </Label>
                <span className="text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                    never stored in chat
                </span>
            </div>
            <p className="text-[0.6875rem] text-muted-foreground">
                on agent <code className="font-mono">{agentSlug}</code>
                {purpose ? ` — ${purpose}` : ''}
            </p>
            <div className="flex gap-1.5">
                <Input
                    id={`secret-inline-${secret}`}
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={value}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setValue(e.currentTarget.value)}
                    placeholder="paste value"
                    disabled={submitting}
                    className="h-7 flex-1 text-xs"
                />
                <Button
                    type="submit"
                    size="xs"
                    disabled={!value || submitting}
                    aria-busy={submitting ? 'true' : undefined}
                >
                    {submitting ? 'Saving…' : mode === 'rotate' ? 'Rotate' : 'Save'}
                </Button>
                <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => onReject('user_cancelled')}
                    disabled={submitting}
                >
                    Cancel
                </Button>
            </div>
            {error ? <p className="text-[0.6875rem] text-destructive-foreground">{error}</p> : null}
        </form>
    )
}
