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
import { lazy, Suspense, useEffect, useRef, useState } from 'react'

import { Button, DialogFooter, Skeleton } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'

import { useTaxonomicFilterContext } from '../headless/context'
import { TaxonomicFilterGroupType } from '../types'
import { MenuFilterHeader } from './Header'
import { CommitFn, MenuFilterEntry } from './types'

const CodeEditorInline = lazy(() =>
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
            {/* No category chips on this page — suppress the Tab hint. */}
            <MenuFilterHeader title="Write SQL expression" onBack={onBack} showTabHint={false} />
            <div className="flex flex-col flex-1 min-h-0">
                <div className="flex flex-col gap-2 p-3 flex-1 min-h-0 overflow-y-auto">
                    {/* 78px matches the legacy HogQLEditor's inline editor. */}
                    <Suspense fallback={<Skeleton className="h-[78px] w-full rounded-md" />}>
                        <CodeEditorInline
                            value={expression}
                            onChange={(v) => setExpression(v ?? '')}
                            language="hogQLExpr"
                            minHeight="78px"
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
                    {/* Arbitrary-value size: `text-xs` is rebound to 14px under
                        the lemon skin, which balloons the hint block. */}
                    <pre className="text-[0.75rem] text-secondary whitespace-pre-wrap font-mono leading-snug m-0">
                        {EXAMPLE_HINTS}
                    </pre>
                    <div className="flex items-baseline justify-between gap-2 text-[0.75rem]">
                        <Link to="https://posthog.com/docs/sql" target="_blank">
                            Learn more about SQL
                        </Link>
                        <span className="text-tertiary">Esc goes back · ⌘+Enter saves</span>
                    </div>
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
