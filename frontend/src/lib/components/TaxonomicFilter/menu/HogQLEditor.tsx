/**
 * HogQL expression editor — opens directly from the dropdown menu, no
 * combobox stop-over. Save commits `{ name, value }` derived from the
 * expression.
 *
 * Real implementation should swap the textarea for `InlineHogQLEditor` /
 * Monaco. The footer + back button + Save / Cancel are stable across
 * either body.
 */
import { useState } from 'react'

import { Button, DialogFooter, Field, FieldContent, FieldDescription, FieldLabel, Textarea } from '@posthog/quill'

import { useTaxonomicFilterContext } from '../headless/context'
import { TaxonomicFilterGroupType } from '../types'
import { MenuFilterHeader } from './Header'
import { CommitFn, MenuFilterEntry } from './types'

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

    const group = groups.find((g) => g.type === TaxonomicFilterGroupType.HogQLExpression)

    const handleSave = (): void => {
        const trimmed = expression.trim()
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
                <div className="flex flex-col gap-4 p-4 flex-1 min-h-0">
                    <Field>
                        <FieldLabel>Expression</FieldLabel>
                        <FieldContent>
                            <Textarea
                                autoFocus
                                rows={6}
                                value={expression}
                                onChange={(e) => setExpression(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Escape') {
                                        e.preventDefault()
                                        onBack()
                                    }
                                    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                                        e.preventDefault()
                                        handleSave()
                                    }
                                }}
                                placeholder="properties.$browser = 'Chrome'"
                                className="font-mono text-xs"
                            />
                            <FieldDescription>
                                Returns this expression as the selected value. Esc goes back without saving. ⌘+Enter
                                saves.
                            </FieldDescription>
                        </FieldContent>
                    </Field>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onBack}>
                        Cancel
                    </Button>
                    <Button variant="primary" disabled={!expression.trim()} onClick={handleSave}>
                        Save
                    </Button>
                </DialogFooter>
            </div>
        </div>
    )
}
