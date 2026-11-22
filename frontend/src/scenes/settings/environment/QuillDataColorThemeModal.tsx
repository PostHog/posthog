import { useActions, useValues } from 'kea'
import { Field as KeaField, Form } from 'kea-forms'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Label,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'

export function QuillDataColorThemeModal(): JSX.Element {
    const { theme, themeChanged, isOpen } = useValues(dataColorThemesModalLogic)
    const { submitTheme, closeModal, addColor, duplicateColor, removeColor } = useActions(dataColorThemesModalLogic)

    const isNew = theme?.id == null
    const isOfficial = theme?.is_global
    const title = isOfficial ? 'Official theme' : isNew ? 'Add theme' : 'Edit theme'

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean, details) => {
                // A stray click outside must not throw away an edited theme.
                if (!open && !(themeChanged && details.reason === 'outside-press')) {
                    closeModal()
                }
            }}
        >
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Form logic={dataColorThemesModalLogic} formKey="theme" className="flex flex-col gap-4">
                        <KeaField name="name" noStyle>
                            {({ id, value, onChange, error }) => (
                                <Field data-invalid={error ? true : undefined}>
                                    <FieldLabel htmlFor={id}>Name</FieldLabel>
                                    <Input
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="My custom theme"
                                        autoFocus={isNew}
                                        disabled={isOfficial}
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                        <div className="flex flex-col gap-2">
                            <Label>Colors</Label>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead className="w-8">
                                            <span className="sr-only">Swatch</span>
                                        </TableHead>
                                        <TableHead>Name</TableHead>
                                        <TableHead>Color</TableHead>
                                        {!isOfficial && (
                                            <TableHead className="w-20">
                                                <span className="sr-only">Actions</span>
                                            </TableHead>
                                        )}
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {theme?.colors?.map((color, index) => (
                                        <TableRow key={index}>
                                            <TableCell>
                                                <span
                                                    className="block size-4 rounded-full border border-border"
                                                    // The swatch shows the user's own color value.
                                                    style={{ backgroundColor: color }}
                                                />
                                            </TableCell>
                                            <TableCell>{`preset-${index + 1}`}</TableCell>
                                            <TableCell>
                                                <KeaField name={['colors', index]} noStyle>
                                                    {({ value, onChange, error }) => (
                                                        <Field data-invalid={error ? true : undefined}>
                                                            <Input
                                                                size="sm"
                                                                className="w-24 font-mono"
                                                                aria-label={`Color ${index + 1}`}
                                                                value={value ?? ''}
                                                                onChange={(event) => onChange(event.target.value)}
                                                                disabled={isOfficial}
                                                            />
                                                            {error && <FieldError>{error}</FieldError>}
                                                        </Field>
                                                    )}
                                                </KeaField>
                                            </TableCell>
                                            {!isOfficial && (
                                                <TableCell>
                                                    <div className="flex gap-1">
                                                        <Button
                                                            size="icon-sm"
                                                            aria-label="Duplicate color"
                                                            tooltip="Duplicate color"
                                                            onClick={() => duplicateColor(index)}
                                                        >
                                                            <IconCopy />
                                                        </Button>
                                                        <Button
                                                            size="icon-sm"
                                                            variant="destructive-outline"
                                                            aria-label="Remove color"
                                                            tooltip="Remove color"
                                                            onClick={() => removeColor(index)}
                                                        >
                                                            <IconTrash />
                                                        </Button>
                                                    </div>
                                                </TableCell>
                                            )}
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                        {!isOfficial && (
                            <div>
                                <Button variant="outline" onClick={addColor}>
                                    <IconPlus />
                                    Add color
                                </Button>
                            </div>
                        )}
                    </Form>
                </DialogBody>
                <DialogFooter>
                    {isOfficial ? (
                        <>
                            <Text size="xs" variant="muted" render={<span className="m-0 me-auto" />}>
                                Official themes can't be edited.
                            </Text>
                            <Button variant="outline" onClick={closeModal}>
                                Close
                            </Button>
                        </>
                    ) : (
                        <Button variant="primary" onClick={submitTheme}>
                            Save
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
