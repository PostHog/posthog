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
    FieldLabel,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    Textarea,
} from '@posthog/quill'

import { CoreEventCategory } from '~/queries/schema/schema-general'

import { CATEGORY_OPTIONS } from './coreEventLabels'

export interface QuillCoreEventDialogProps {
    open: boolean
    editing: boolean
    name: string
    description: string
    category: CoreEventCategory | null
    /** The event, action or data warehouse table picker, shared with the Lemon modal. */
    filterPicker: JSX.Element
    onNameChange: (name: string) => void
    onDescriptionChange: (description: string) => void
    onCategoryChange: (category: CoreEventCategory | null) => void
    onSave: () => void
    onClose: () => void
    saveDisabledReason: string | undefined
}

export function QuillCoreEventDialog({
    open,
    editing,
    name,
    description,
    category,
    filterPicker,
    onNameChange,
    onDescriptionChange,
    onCategoryChange,
    onSave,
    onClose,
    saveDisabledReason,
}: QuillCoreEventDialogProps): JSX.Element {
    const id = useId()

    return (
        <Dialog
            open={open}
            onOpenChange={(nextOpen) => {
                if (!nextOpen) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>{editing ? 'Edit core event' : 'Add core event'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Field>
                            <FieldLabel htmlFor={`${id}-name`}>Name</FieldLabel>
                            <Input
                                id={`${id}-name`}
                                value={name}
                                onChange={(event) => onNameChange(event.target.value)}
                                placeholder="e.g., Purchase, Sign up"
                            />
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={`${id}-description`}>Description (optional)</FieldLabel>
                            <Textarea
                                id={`${id}-description`}
                                value={description}
                                onChange={(event) => onDescriptionChange(event.target.value)}
                                placeholder="Describe what this core event tracks"
                                rows={2}
                            />
                        </Field>
                        <Field>
                            <Label>Event, action, or data warehouse table</Label>
                            {filterPicker}
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={`${id}-category`}>Category</FieldLabel>
                            <Select<CoreEventCategory | null>
                                items={CATEGORY_OPTIONS}
                                value={category}
                                onValueChange={onCategoryChange}
                            >
                                <SelectTrigger id={`${id}-category`} className="w-full">
                                    <SelectValue placeholder="Select a category" />
                                </SelectTrigger>
                                <SelectContent>
                                    {CATEGORY_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            <span className="flex flex-col">
                                                <span>{option.label}</span>
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    {option.description}
                                                </Text>
                                            </span>
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={onSave} disabledReason={saveDisabledReason}>
                        {editing ? 'Update' : 'Add'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
