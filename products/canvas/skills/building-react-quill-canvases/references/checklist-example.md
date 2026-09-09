# A known-good checklist canvas

A complete, buildable checklist/runbook canvas, verified against the real canvas builder.
Start from it whenever the request is a checklist, QA runbook, launch plan, onboarding sequence, or any list of steps people work through and tick off — keep its structure and replace the content.

The parts that break when improvised, in the order they matter:

- **Content lives in its own data module** (`src/plan.ts`), typed, separate from the component. Editing the steps later is a data edit, not a component rewrite — and a follow-up request like "add a step" touches one file.
- **One shared `ph.state` key per step** (`step:<id>`), holding `{ done, note }`. Progress is team-visible and survives reloads; per-key writes mean two people ticking different steps don't clobber each other the way one big list value would. An entry that returns to blank is deleted with a null write, so state never accumulates empty rows. Declare `state: ["shared"]` in `capabilities.posthog`.
- **A ref alongside React state for updates.** Note saves are debounced per step; checkbox saves are immediate. Both go through one `update()` that reads the latest entry from a ref, so a keystroke and a checkbox click in the same debounce window can't overwrite each other with stale values.
- **Loading and failure are visible states.** Skeletons while `ph.state.list` resolves; a load failure says progress won't be remembered; a save failure says a change didn't save. Save errors are keyed per step, so one step's later success can't hide another step's failed write. Never fall through to an empty checklist that looks freshly reset.
- **Every step states its expected outcome.** A checkbox alone tells the runner what to do, not how to know it worked — the `expect` line is what makes the list a runbook instead of a todo list. A notes field per step captures deviations where they happened.
- **Destructive reset asks twice, then cancels pending saves.** The reset button swaps to a confirm button instead of clearing shared progress on one click, and the reset clears every pending debounced timer first so an in-flight note save can't write itself back after the keys are deleted.

Capabilities for this project: the full `capabilities.posthog` shape with `state: ["shared"]` and everything else empty (`insights: []`, `inlineQueries: false`, `captureEvents: []`, `actions: []`, `network.origins: []`). Keep `index.html` and `dependencies` exactly as `canvas-source-retrieve` returned them.

## The content module (`src/plan.ts`)

Replace the sample sections with the user's actual steps. Keep the shape: stable ids (they key the persisted state — renaming an id orphans its saved progress), an `expect` on every step, optional `detail`, `cmd`, and `tag`.

```ts
export type Step = {
  id: string
  title: string
  detail?: string
  cmd?: string
  expect: string
  tag?: string
}

export type Section = {
  id: string
  title: string
  blurb: string
  steps: Step[]
}

export const SECTIONS: Section[] = [
  {
    id: 'setup',
    title: 'Environment',
    blurb: 'Get a clean build running before touching the flows below.',
    steps: [
      {
        id: 'setup-build',
        title: 'Build and boot the app',
        cmd: 'pnpm install && pnpm dev',
        expect: 'The app opens with no errors in the console.',
      },
      {
        id: 'setup-health',
        title: 'Check the API is up',
        cmd: 'curl -s https://api.example.com/healthz',
        expect: 'A 200 response with {"status":"ok"}.',
        tag: 'blocking',
      },
    ],
  },
  {
    id: 'flows',
    title: 'Core flows',
    blurb: 'The paths most users hit. Each step assumes the environment section passed.',
    steps: [
      {
        id: 'flows-signup',
        title: 'Sign up a fresh account',
        detail: 'Use a throwaway address so the welcome email path runs end to end.',
        expect: 'The account lands on the onboarding screen and the welcome email arrives.',
      },
      {
        id: 'flows-invite',
        title: 'Invite a teammate',
        expect: 'The invite email arrives and its accept link joins the right workspace.',
      },
      {
        id: 'flows-export',
        title: 'Export a report',
        detail: 'Any dashboard will do; the point is that the download completes.',
        expect: 'A CSV downloads and opens with the expected columns.',
        tag: 'flaky area',
      },
    ],
  },
]

export const TOTAL_STEPS = SECTIONS.reduce((n, s) => n + s.steps.length, 0)
```

## The component (`src/canvas.tsx`)

```tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Checkbox,
  Heading,
  Label,
  Skeleton,
  Textarea,
} from '@posthog/quill'
import { Check, ChevronDown, ChevronRight, Copy, RotateCcw } from 'lucide-react'
import { SECTIONS, TOTAL_STEPS } from './plan'

type Entry = { done: boolean; note: string }
type Entries = Record<string, Entry>

const PREFIX = 'step:'
const BLANK: Entry = { done: false, note: '' }
const RESET_KEY = '*reset'

const errorMessage = (err: unknown): string => String((err as { message?: string })?.message ?? err)

function CommandBlock({
  id,
  cmd,
  copied,
  onCopy,
}: {
  id: string
  cmd: string
  copied: string | null
  onCopy: (id: string, text: string) => Promise<void>
}) {
  const ok = copied === id
  const failed = copied === 'fail:' + id
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void onCopy(id, cmd)}>
          {ok ? <Check size={13} /> : <Copy size={13} />}
          {ok ? 'Copied' : failed ? 'Select it manually' : 'Copy'}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs leading-relaxed text-foreground">
        <code>{cmd}</code>
      </pre>
    </div>
  )
}

export default function Canvas() {
  const [entries, setEntries] = useState<Entries>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ setup: true })
  const [hideDone, setHideDone] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)

  const entriesRef = useRef<Entries>({})
  const timers = useRef<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false
    const load = async (): Promise<void> => {
      try {
        const rows = await ph.state.list({ scope: 'shared' })
        if (cancelled) {
          return
        }
        const next: Entries = {}
        for (const row of rows ?? []) {
          const key = row?.key
          const value = row?.value
          if (typeof key === 'string' && key.startsWith(PREFIX) && value) {
            next[key.slice(PREFIX.length)] = {
              done: Boolean(value.done),
              note: typeof value.note === 'string' ? value.note : '',
            }
          }
        }
        entriesRef.current = next
        setEntries(next)
        setLoading(false)
      } catch (err) {
        if (cancelled) {
          return
        }
        setLoading(false)
        setLoadError(errorMessage(err))
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const pending = timers.current
    return () => {
      for (const id of Object.keys(pending)) {
        window.clearTimeout(pending[id])
      }
    }
  }, [])

  // Save failures are tracked per step: a later success on one step must not
  // hide another step's failed write.
  const persist = async (stepId: string, entry: Entry): Promise<void> => {
    const empty = !entry.done && entry.note.trim() === ''
    try {
      await ph.state.set(PREFIX + stepId, empty ? null : entry, { scope: 'shared' })
      setSaveErrors(({ [stepId]: _cleared, ...rest }) => rest)
    } catch (err) {
      setSaveErrors((prev) => ({ ...prev, [stepId]: errorMessage(err) }))
    }
  }

  // Keep a ref alongside state so a note keystroke and a checkbox click in the
  // same debounce window can't read each other's stale value.
  const update = (stepId: string, patch: Partial<Entry>, delay: number) => {
    const next = { ...(entriesRef.current[stepId] ?? BLANK), ...patch }
    entriesRef.current = { ...entriesRef.current, [stepId]: next }
    setEntries(entriesRef.current)
    window.clearTimeout(timers.current[stepId])
    if (delay === 0) {
      void persist(stepId, next)
    } else {
      timers.current[stepId] = window.setTimeout(() => void persist(stepId, next), delay)
    }
  }

  const onCopy = async (id: string, text: string): Promise<void> => {
    const flash = (value: string, ms: number) => {
      setCopied(value)
      window.setTimeout(() => setCopied((c) => (c === value ? null : c)), ms)
    }
    try {
      await navigator.clipboard.writeText(text)
      flash(id, 1500)
    } catch {
      flash('fail:' + id, 2500)
    }
  }

  const resetAll = async (): Promise<void> => {
    // Cancel pending debounced saves first, or a note typed just before the
    // reset writes itself back after the keys are cleared.
    for (const id of Object.keys(timers.current)) {
      window.clearTimeout(timers.current[id])
    }
    timers.current = {}
    try {
      const keys = Object.keys(entriesRef.current)
      await Promise.all(keys.map((k) => ph.state.set(PREFIX + k, null, { scope: 'shared' })))
      entriesRef.current = {}
      setEntries({})
      setConfirmReset(false)
      setSaveErrors({})
    } catch (err) {
      setSaveErrors((prev) => ({ ...prev, [RESET_KEY]: errorMessage(err) }))
    }
  }

  const doneCount = useMemo(() => Object.values(entries).filter((e) => e.done).length, [entries])
  const pct = TOTAL_STEPS ? Math.round((doneCount / TOTAL_STEPS) * 100) : 0
  const allOpen = SECTIONS.every((s) => expanded[s.id])

  const toggleAll = () => {
    if (allOpen) {
      setExpanded({})
      return
    }
    const next: Record<string, boolean> = {}
    for (const s of SECTIONS) {
      next[s.id] = true
    }
    setExpanded(next)
  }

  return (
    <div className="h-screen overflow-y-auto bg-background">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Heading size="xl">Release QA</Heading>
            <p className="mt-1 text-sm text-muted-foreground">
              Work down the page: each section assumes the one above it passed. Checkmarks and notes are shared with
              everyone who opens this canvas, and save as you type.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" size="sm" onClick={toggleAll}>
              {allOpen ? 'Collapse all' : 'Expand all'}
            </Button>
            {confirmReset ? (
              <Button variant="primary" size="sm" onClick={() => void resetAll()}>
                Confirm reset
              </Button>
            ) : (
              <Button variant="outline" size="sm" onClick={() => setConfirmReset(true)}>
                <RotateCcw size={14} />
                Reset
              </Button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: pct + '%' }} />
          </div>
          <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
            {doneCount} of {TOTAL_STEPS} done
          </span>
        </div>

        <div className="flex items-center gap-2">
          <Checkbox id="hide-done" checked={hideDone} onCheckedChange={(v) => setHideDone(Boolean(v))} />
          <Label htmlFor="hide-done">Hide finished steps</Label>
        </div>

        {loadError && (
          <Card size="sm">
            <CardContent>
              <p className="text-sm text-destructive-foreground">
                Could not load saved progress: {loadError}. Your checkmarks and notes will not be remembered until this
                clears.
              </p>
            </CardContent>
          </Card>
        )}
        {Object.keys(saveErrors).length > 0 && (
          <Card size="sm">
            <CardContent>
              <p className="text-sm text-destructive-foreground">
                A change did not save: {Object.values(saveErrors)[0]}
              </p>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          SECTIONS.map((section, sectionIndex) => {
            const sectionDone = section.steps.filter((s) => entries[s.id]?.done).length
            const complete = sectionDone === section.steps.length
            const open = Boolean(expanded[section.id])
            const visible = hideDone ? section.steps.filter((s) => !entries[s.id]?.done) : section.steps

            return (
              <Card key={section.id} size="sm">
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setExpanded((prev) => ({
                            ...prev,
                            [section.id]: !prev[section.id],
                          }))
                        }
                      >
                        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </Button>
                      <div className="min-w-0">
                        <CardTitle>
                          {sectionIndex + 1}. {section.title}
                        </CardTitle>
                        <p className="mt-1 text-xs text-muted-foreground">{section.blurb}</p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge variant={complete ? 'success' : undefined}>
                        {sectionDone}/{section.steps.length}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>

                {open && (
                  <CardContent>
                    {visible.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        Every step here is done. Untick Hide finished steps to see them.
                      </p>
                    ) : (
                      <div className="flex flex-col gap-4">
                        {visible.map((step) => {
                          const entry = entries[step.id] ?? BLANK
                          const number = section.steps.findIndex((s) => s.id === step.id) + 1
                          return (
                            <div
                              key={step.id}
                              className="flex gap-3 border-t border-border pt-4 first:border-t-0 first:pt-0"
                            >
                              <div className="pt-0.5">
                                <Checkbox
                                  checked={entry.done}
                                  onCheckedChange={(v) => update(step.id, { done: Boolean(v) }, 0)}
                                />
                              </div>
                              <div className="flex min-w-0 flex-1 flex-col gap-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span
                                    className={
                                      entry.done
                                        ? 'text-sm font-medium text-muted-foreground line-through'
                                        : 'text-sm font-medium text-foreground'
                                    }
                                  >
                                    {sectionIndex + 1}.{number} {step.title}
                                  </span>
                                  {step.tag && <Badge>{step.tag}</Badge>}
                                </div>

                                {step.detail && <p className="text-sm text-muted-foreground">{step.detail}</p>}

                                {step.cmd && (
                                  <CommandBlock id={step.id} cmd={step.cmd} copied={copied} onCopy={onCopy} />
                                )}

                                <div className="flex gap-2 rounded-md bg-muted p-2">
                                  <span className="shrink-0 text-xs font-medium text-muted-foreground">Expect</span>
                                  <span className="text-xs text-foreground">{step.expect}</span>
                                </div>

                                <Textarea
                                  value={entry.note}
                                  placeholder="Notes, deviations, anything you found"
                                  onChange={(e) => update(step.id, { note: e.target.value }, 700)}
                                />
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </CardContent>
                )}
              </Card>
            )
          })
        )}
      </div>
    </div>
  )
}
```

Adapt freely above the persistence layer: a "Before you start" card of prerequisites under the header, a per-section owner badge, or ordering hints all fit the same shape. What should survive every adaptation: the per-step shared-state keys, the ref-alongside-state update path, the visible load/save failure states, and the expect line on every step.
