import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** Monospace SQL with a copy button. The SQL arrives with its literal values masked. */
export function WarehouseSqlBlock({ sql }: { sql: string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-start gap-2 rounded-md border bg-surface-secondary p-2">
            <pre className="m-0 max-h-64 min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-words font-mono text-xs">
                {sql}
            </pre>
            <Button
                size="icon-sm"
                aria-label="Copy SQL"
                data-attr="warehouse-query-copy-sql"
                onClick={() => {
                    posthog.capture('warehouse query sql copied')
                    void copyToClipboard(sql, 'SQL')
                }}
            >
                <IconCopy />
            </Button>
        </div>
    )
}
