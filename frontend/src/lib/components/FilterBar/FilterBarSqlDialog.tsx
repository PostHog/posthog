import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Textarea,
} from '@posthog/quill'

import { PropertyFilterType } from '~/types'

import { filterBarLogic } from './filterBarLogic'

/** Writes or edits a SQL expression filter. The expression is the filter, so it is complete the moment it is saved. */
export function FilterBarSqlDialog(): JSX.Element {
    const { sqlDialog, items } = useValues(filterBarLogic)
    const { closeSqlDialog, addFilter, setItemSql } = useActions(filterBarLogic)
    const editing = items.find((item) => item.id === sqlDialog.itemId) ?? null
    const [expression, setExpression] = useState('')
    const trimmed = expression.trim()

    useEffect(() => {
        if (sqlDialog.open) {
            setExpression(editing?.filter.type === PropertyFilterType.HogQL ? editing.filter.key : '')
        }
    }, [sqlDialog.open, editing])

    const submit = (): void => {
        if (!trimmed) {
            return
        }
        if (editing) {
            setItemSql(editing.id, trimmed)
        } else {
            addFilter({ type: PropertyFilterType.HogQL, key: trimmed, value: null }, 'sql')
        }
        closeSqlDialog()
    }

    return (
        <Dialog open={sqlDialog.open} onOpenChange={(open: boolean) => !open && closeSqlDialog()}>
            <DialogContent data-attr="filter-bar-sql-dialog">
                <form
                    className="contents"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submit()
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>{editing ? 'Edit SQL expression' : 'Filter by SQL expression'}</DialogTitle>
                        <DialogDescription>
                            An expression that is true for the events to keep, such as{' '}
                            <code>properties.$browser_version &gt; 100</code>.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <Field>
                            <FieldLabel htmlFor="filter-bar-sql-expression">Expression</FieldLabel>
                            <Textarea
                                id="filter-bar-sql-expression"
                                autoFocus
                                rows={4}
                                className="font-mono"
                                value={expression}
                                onChange={(event: React.ChangeEvent<HTMLTextAreaElement>) =>
                                    setExpression(event.target.value)
                                }
                                onKeyDown={(event: React.KeyboardEvent<HTMLTextAreaElement>) => {
                                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                                        event.preventDefault()
                                        submit()
                                    }
                                }}
                                placeholder="properties.$browser_version > 100"
                                data-attr="filter-bar-sql-expression"
                            />
                        </Field>
                    </DialogBody>
                    <DialogFooter>
                        <DialogClose render={<Button variant="outline" data-attr="filter-bar-sql-cancel" />}>
                            Cancel
                        </DialogClose>
                        <Button
                            type="submit"
                            variant="primary"
                            disabledReason={trimmed ? undefined : 'Type an expression first'}
                            data-attr="filter-bar-sql-apply"
                        >
                            {editing ? 'Save' : 'Add filter'}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
