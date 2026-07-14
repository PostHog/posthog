/**
 * HogQL expression editor — opens directly from the dropdown menu, no
 * combobox stop-over. Save commits `{ name, value }` derived from the
 * expression.
 *
 * The Monaco editor (`CodeEditorInline`) is loaded lazily so the
 * Monaco bundle isn't pulled into the main chunk just to keep the
 * filter menu warm. While the chunk loads, a Skeleton fills the
 * editor slot. Esc and ⌘+Enter are wired through Monaco's command
 * registry — Esc only fires `onBack` when no suggestion / find
 * widget is open so it still closes those first like users expect.
 */
import { Suspense, useEffect, useRef, useState } from 'react'

import { Button, DialogFooter, Field, FieldContent, FieldDescription, FieldLabel, Skeleton } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { useTaxonomicFilterContext } from '../headless/context'
import { TaxonomicFilterGroupType } from '../types'
import { MenuFilterHeader } from './Header'
import { CommitFn, MenuFilterEntry } from './types'

const CodeEditorInline = lazyWithRetry(() =>
    import('lib/monaco/CodeEditorInline').then((m) => ({ default: m.CodeEditorInline }))
)

const EXAMPLE_HINTS = `Enter SQL expression, such as:
- properties.$current_url
- person.properties.email
- toInt(properties.\`Long Field Name\`) * 10
- concat(event, ' ', distinct_id)`

export interface MenuFilterHogQLEditorProps {
    onCommit: CommitFn
    onBack: () => void
    /** Pre-fill the editor (e.g. when re-editing an existing expression). */
    initialExpression?: string
}

export function MenuFilterHogQLEditor({
    onCommit,
    onBack,
    initialExpression = '',
}: MenuFilterHogQLEditorProps): JSX.Element {
    const { groups } = useTaxonomicFilterContext()
    const [expression, setExpression] = useState(initialExpression)
    // Monaco's `addAction` registers handlers at editor-mount time and
    // captures whatever `onPressCmdEnter` referenced then. Without a ref
    // we'd permanently call the first render's `commit` (with the
    // initial empty expression), which is why ⌘+Enter looked broken.
    const expressionRef = useRef(expression)
    useEffect(() => {
        expressionRef.current = expression
    }, [expression])

    const group = groups.find((g) => g.type === TaxonomicFilterGroupType.HogQLExpression)

    const commit = (raw: string): void => {
        // When Cmd+Enter fires without a selection, Monaco passes an
        // empty string as `highlightedText`. Fall back to the live
        // editor value via the ref so the save still goes through.
        const value = raw.length > 0 ? raw : expressionRef.current
        const trimmed = value.trim()
        if (!trimmed || !group) {
            return
        }
        const entry: MenuFilterEntry = {
            item: { name: trimmed, value: trimmed } as never,
            group,
            name: trimmed,
        }
        onCommit(entry, { name: trimmed, value: trimmed })
    }

    return (
        <div className="flex flex-col flex-1 min-h-0">
            <MenuFilterHeader title="Write SQL expression" onBack={onBack} />
            <div className="flex flex-col flex-1 min-h-0">
                <div className="flex flex-col gap-4 p-4 flex-1 min-h-0 overflow-y-auto">
                    <Field>
                        <FieldLabel>Expression</FieldLabel>
                        <FieldContent className="gap-4">
                            <Suspense fallback={<Skeleton className="h-[120px] w-full rounded-md" />}>
                                <CodeEditorInline
                                    value={expression}
                                    onChange={(v) => setExpression(v ?? '')}
                                    language="hogQLExpr"
                                    minHeight="120px"
                                    autoFocus
                                    onPressCmdEnter={(value) => commit(value)}
                                    onMount={(editor, monaco) => {
                                        // Esc → onBack, but only when Monaco
                                        // isn't in a state where Esc has its
                                        // own meaning (suggestions, find,
                                        // snippet) — otherwise we'd swallow
                                        // intellisense dismissal.
                                        editor.addCommand(
                                            monaco.KeyCode.Escape,
                                            () => onBack(),
                                            '!suggestWidgetVisible && !findWidgetVisible && !inSnippetMode'
                                        )
                                    }}
                                />
                            </Suspense>
                            <FieldDescription>
                                <pre className="text-xs text-secondary whitespace-pre-wrap font-mono leading-snug m-0">
                                    {EXAMPLE_HINTS}
                                </pre>
                                <div className="mt-2 text-xs">
                                    <Link
                                        to="https://posthog.com/docs/sql"
                                        target="_blank"
                                        className="underline text-primary"
                                    >
                                        Learn more about SQL
                                    </Link>
                                </div>
                                <div className="mt-2 text-xs text-tertiary">
                                    Esc goes back without saving. ⌘+Enter saves.
                                </div>
                            </FieldDescription>
                        </FieldContent>
                    </Field>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onBack}>
                        Cancel
                    </Button>
                    <Button variant="primary" disabled={!expression.trim()} onClick={() => commit(expression)}>
                        Add SQL expression
                    </Button>
                </DialogFooter>
            </div>
        </div>
    )
}
