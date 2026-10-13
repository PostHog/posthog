import { ChangeEvent, KeyboardEvent, useEffect, useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { Button, Kbd, KbdGroup, Text, Textarea } from '@posthog/quill'

import { SQL_COLUMN_HINTS } from '../../../editing/blockLibrary/blockSql'
import { InspectorField } from './InspectorField'

/** The HogQL behind a block. It runs on Cmd+Enter or the button, not on every key. */
export function SqlField({
    type,
    sql,
    onCommit,
}: {
    type: string
    sql: string
    onCommit: (sql: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState(sql)
    useEffect(() => setDraft(sql), [sql])
    const changed = draft.trim() !== sql.trim()
    return (
        <InspectorField
            label="HogQL"
            hint={
                <>
                    {SQL_COLUMN_HINTS[type]} Keep <code className="font-mono">{'{filters}'}</code> in the WHERE clause
                    so the canvas date range and filters apply.
                </>
            }
        >
            <Textarea
                value={draft}
                rows={8}
                aria-label="HogQL"
                spellCheck={false}
                className="font-mono"
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setDraft(event.target.value)}
                onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && changed) {
                        onCommit(draft)
                    }
                }}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-1">
                    <KbdGroup>
                        <Kbd>{navigator.platform.toLowerCase().includes('mac') ? '⌘' : 'Ctrl'}</Kbd>
                        <Kbd>↵</Kbd>
                    </KbdGroup>
                    <span>to run</span>
                </Text>
                <Button
                    variant="primary"
                    size="sm"
                    disabled={!changed}
                    onClick={() => onCommit(draft)}
                    data-attr="canvas-block-sql-run"
                >
                    <IconPlay />
                    Run query
                </Button>
            </div>
        </InspectorField>
    )
}
