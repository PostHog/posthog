import { useId } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldLabel,
    FieldTitle,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor } from '../Editor'
import { MacroDraft, MacroVisibility } from './supportMacrosLogic'

export function QuillMacroFormDialog({
    macroDraft,
    variables,
    macroSaving,
    isSomeoneElses,
    saveDisabledReason,
    onEditorCreate,
    onInsertVariable,
    onSave,
    onClose,
    onNameChange,
    onShortcutChange,
    onVisibilityChange,
    onBodyEmptyChange,
    onUploadingChange,
}: {
    macroDraft: MacroDraft
    variables: { label: string; token: string }[]
    macroSaving: boolean
    isSomeoneElses: boolean
    saveDisabledReason: string | null | undefined
    onEditorCreate: (editor: RichContentEditorType) => void
    onInsertVariable: (token: string) => void
    onSave: () => void
    onClose: () => void
    onNameChange: (name: string) => void
    onShortcutChange: (shortcut: string) => void
    onVisibilityChange: (visibility: MacroVisibility) => void
    onBodyEmptyChange: (isEmpty: boolean) => void
    onUploadingChange: (uploading: boolean) => void
}): JSX.Element {
    const idPrefix = useId()
    const nameId = `${idPrefix}-name`
    const shortcutId = `${idPrefix}-shortcut`

    return (
        <Dialog
            open
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{macroDraft.id ? 'Edit macro' : 'New macro'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Field>
                            <FieldLabel htmlFor={nameId}>Name</FieldLabel>
                            <Input
                                id={nameId}
                                value={macroDraft.name}
                                onChange={(event) => onNameChange(event.target.value)}
                                placeholder="Cancellation"
                                autoFocus
                            />
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={shortcutId}>Shortcut</FieldLabel>
                            <InputGroup>
                                <InputGroupAddon align="inline-start">
                                    <InputGroupText>/</InputGroupText>
                                </InputGroupAddon>
                                <InputGroupInput
                                    id={shortcutId}
                                    value={macroDraft.shortcut}
                                    onChange={(event) => onShortcutChange(event.target.value)}
                                    placeholder="cancel"
                                />
                            </InputGroup>
                            <FieldDescription>
                                Letters, numbers, and hyphens. Leave this blank to keep the macro in the menu only.
                                Agents insert it by typing / followed by the shortcut.
                            </FieldDescription>
                        </Field>
                        <Field>
                            <FieldTitle>Visible to</FieldTitle>
                            <ToggleGroup
                                variant="outline"
                                aria-label="Visible to"
                                value={[macroDraft.visibility]}
                                onValueChange={(next: string[]) => {
                                    if (next[0]) {
                                        onVisibilityChange(next[0] as MacroVisibility)
                                    }
                                }}
                                data-attr="support-macro-visibility"
                            >
                                <ToggleGroupItem value="shared">Everyone</ToggleGroupItem>
                                <ToggleGroupItem
                                    value="personal"
                                    disabledReason={
                                        isSomeoneElses
                                            ? 'Only the person who created this macro can make it personal'
                                            : undefined
                                    }
                                >
                                    Only me
                                </ToggleGroupItem>
                            </ToggleGroup>
                        </Field>
                        <SupportEditor
                            key={macroDraft.id ?? 'new'}
                            initialContent={null}
                            minRows={6}
                            placeholder="Hi {{customer.first_name}}"
                            onUpdate={onBodyEmptyChange}
                            onUploadingChange={onUploadingChange}
                            onCreate={onEditorCreate}
                        />
                        <div className="flex flex-wrap gap-1">
                            {variables.map((variable) => (
                                <Button
                                    key={variable.token}
                                    variant="outline"
                                    size="sm"
                                    onClick={() => onInsertVariable(variable.token)}
                                >
                                    {variable.label}
                                </Button>
                            ))}
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabled={macroSaving}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSave}
                        loading={macroSaving}
                        disabledReason={saveDisabledReason}
                        data-attr="support-macro-save"
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
