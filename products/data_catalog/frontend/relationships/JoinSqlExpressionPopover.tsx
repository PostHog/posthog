import { useRef, useState } from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { escapeDottedHogQLIdentifier } from 'lib/utils/hogql'

import { NodeKind } from '~/queries/schema/schema-general'

interface JoinSqlExpressionPopoverProps {
    value: string
    tableName: string
    placeholder: string
    onChange: (value: string) => void
    disabledReason?: string
    ariaLabel: string
}

export function JoinSqlExpressionPopover({
    value,
    tableName,
    placeholder,
    onChange,
    disabledReason,
    ariaLabel,
}: JoinSqlExpressionPopoverProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [draft, setDraft] = useState(value)
    const latestDraft = useRef(value)
    const updateDraft = (nextDraft: string): void => {
        latestDraft.current = nextDraft
        setDraft(nextDraft)
    }
    const apply = (expression: string): void => {
        onChange(expression)
        setOpen(false)
    }

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                setOpen(nextOpen)
                if (nextOpen) {
                    updateDraft(value)
                }
            }}
        >
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        className="h-8 max-w-60 font-mono"
                        aria-label={ariaLabel}
                        disabledReason={disabledReason}
                    />
                }
            >
                <span className="min-w-0 truncate">{value || 'Enter SQL expression'}</span>
            </PopoverTrigger>
            <PopoverContent align="start" className="flex w-120 flex-col gap-2">
                <CodeEditorInline
                    data-attr="data-catalog-join-sql-editor"
                    value={draft}
                    onChange={(nextValue) => updateDraft(nextValue ?? '')}
                    language="hogQLExpr"
                    minHeight="78px"
                    autoFocus
                    sourceQuery={{
                        kind: NodeKind.HogQLQuery,
                        query: `SELECT * FROM ${escapeDottedHogQLIdentifier(tableName)}`,
                    }}
                    onPressCmdEnter={() => apply(latestDraft.current)}
                />
                <Text size="xs" variant="muted" render={<pre className="m-0" />}>
                    {placeholder}
                </Text>
                <Button
                    variant="primary"
                    disabledReason={draft ? undefined : 'Enter a SQL expression'}
                    onClick={() => apply(draft)}
                    data-attr="data-catalog-join-sql-update"
                >
                    Update SQL expression
                </Button>
                <Button
                    variant="link"
                    size="inline"
                    className="self-end"
                    render={<LinkPrimitive to="https://posthog.com/docs/sql" target="_blank" />}
                >
                    Learn more about SQL
                </Button>
            </PopoverContent>
        </Popover>
    )
}
