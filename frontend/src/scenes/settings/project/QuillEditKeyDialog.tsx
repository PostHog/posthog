import { Form, Field as KeaField } from 'kea-forms'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import type { ProjectSecretAPIKeyScopePreset } from 'lib/scopes'

import { projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'

export function QuillEditKeyDialog({
    isNew,
    isOpen,
    onClose,
    hasUnsavedInput,
    isSubmitting,
    submitDisabledReason,
    onSubmit,
    availablePresets,
    searchTerm,
    onSearchTermChange,
    scopeRows,
}: {
    isNew: boolean
    isOpen: boolean
    onClose: () => void
    hasUnsavedInput: boolean
    isSubmitting: boolean
    submitDisabledReason: string | undefined
    onSubmit: () => void
    availablePresets: ProjectSecretAPIKeyScopePreset[]
    searchTerm: string
    onSearchTermChange: (searchTerm: string) => void
    scopeRows: JSX.Element[]
}): JSX.Element {
    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open, details) => {
                // A stray click outside must not throw away a half-filled key.
                if (!open && !(hasUnsavedInput && details.reason === 'outside-press')) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>{`${isNew ? 'Create' : 'Edit'} project secret API key`}</DialogTitle>
                    <DialogDescription>
                        Project secret API keys have limited scopes. Select only the permissions needed.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Form logic={projectSecretAPIKeysLogic} formKey="editingKey" className="flex flex-col gap-4">
                        <KeaField name="label" noStyle>
                            {({ id, value, onChange, error }) => (
                                <Field data-invalid={error ? true : undefined}>
                                    <FieldLabel htmlFor={id}>Label</FieldLabel>
                                    <Input
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="e.g., CI/CD Pipeline"
                                        maxLength={40}
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                        <div className="flex flex-col gap-2">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <Label>Scopes</Label>
                                <KeaField name="preset" noStyle>
                                    {({ value, onChange }) => (
                                        <Select
                                            items={availablePresets}
                                            value={value ?? null}
                                            onValueChange={(preset: string | null) => onChange(preset ?? undefined)}
                                        >
                                            <SelectTrigger aria-label="Scope preset">
                                                <SelectValue placeholder="Select preset" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                {availablePresets.map((preset) => (
                                                    <SelectItem key={preset.value} value={preset.value}>
                                                        {preset.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    )}
                                </KeaField>
                            </div>
                            <Input
                                type="search"
                                placeholder="Search scopes..."
                                aria-label="Search scopes"
                                value={searchTerm}
                                onChange={(event) => onSearchTermChange(event.target.value)}
                            />
                            <KeaField name="scopes" noStyle>
                                {({ error }) => (
                                    <Field data-invalid={error ? true : undefined}>
                                        <div className="flex flex-col gap-2">
                                            {scopeRows.length === 0 ? (
                                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                    No scopes match "{searchTerm}"
                                                </Text>
                                            ) : (
                                                scopeRows
                                            )}
                                        </div>
                                        {error && <FieldError>{error}</FieldError>}
                                    </Field>
                                )}
                            </KeaField>
                        </div>
                    </Form>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={isSubmitting}
                        disabledReason={submitDisabledReason}
                        onClick={onSubmit}
                    >
                        {isNew ? 'Create key' : 'Save'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
