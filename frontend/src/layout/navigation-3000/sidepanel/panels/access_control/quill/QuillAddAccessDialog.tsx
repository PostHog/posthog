import { useValues } from 'kea'
import { useEffect, useId, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldGroup,
    FieldLabel,
    FieldTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    useComboboxAnchor,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'

import { AccessControlLevel } from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { QuillAccessLevelSelect } from './QuillAccessLevelSelect'

// The same cap as the LemonUI member picker.
const MAX_PICKER_RESULTS = 100

export interface AddAccessOption {
    key: string
    /** What the search matches against. */
    searchLabel: string
    name: string
    /** Set for members, so their row shows an avatar and email. */
    email?: string
}

interface QuillAddAccessDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    pickerLabel: string
    placeholder: string
    emptyText: string
    onAdd: (newValues: string[], level: AccessControlLevel) => Promise<void>
    options: AddAccessOption[]
}

export function QuillAddAccessDialog(props: QuillAddAccessDialogProps): JSX.Element {
    const { availableLevels, canEditAccessControls } = useValues(accessControlLogic)
    const [items, setItems] = useState<string[]>([])
    const [level, setLevel] = useState<AccessControlLevel | null>(availableLevels[0] ?? null)
    const [submitting, setSubmitting] = useState(false)
    const pickerId = useId()

    useEffect(() => {
        setLevel(availableLevels[0] ?? null)
    }, [availableLevels])

    const optionsByKey = Object.fromEntries(props.options.map((option) => [option.key, option]))
    const disabledReason = !canEditAccessControls
        ? 'You cannot edit this'
        : !items.length || !level
          ? 'Choose who to add and at what level'
          : undefined

    const onSubmit = (): void => {
        if (!items.length || !level) {
            return
        }
        setSubmitting(true)
        void props
            .onAdd(items, level)
            .then(() => {
                setItems([])
                setLevel(availableLevels[0] ?? null)
            })
            .finally(() => setSubmitting(false))
    }

    return (
        <Dialog open={props.open} onOpenChange={props.onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Add access</DialogTitle>
                    <DialogDescription>Allow other users or roles to access this resource</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor={pickerId}>{props.pickerLabel}</FieldLabel>
                            <Combobox<string, true>
                                multiple
                                autoHighlight
                                items={props.options.map((option) => option.key)}
                                // Large organizations have thousands of members, so the list shows the top matches only.
                                limit={MAX_PICKER_RESULTS}
                                itemToStringLabel={(key: string) => optionsByKey[key]?.searchLabel ?? key}
                                value={items}
                                onValueChange={(next: string[]) => setItems(next ?? [])}
                                disabled={!canEditAccessControls}
                            >
                                <AddAccessPicker
                                    id={pickerId}
                                    placeholder={props.placeholder}
                                    emptyText={props.options.length ? 'No matches' : props.emptyText}
                                    optionsByKey={optionsByKey}
                                    disabled={!canEditAccessControls}
                                />
                            </Combobox>
                        </Field>
                        <Field>
                            <FieldTitle>Access level</FieldTitle>
                            <div>
                                <QuillAccessLevelSelect levels={availableLevels} level={level} onChange={setLevel} />
                            </div>
                        </Field>
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => props.onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="primary"
                                    loading={submitting}
                                    disabled={!!disabledReason}
                                    onClick={onSubmit}
                                    data-attr="access-control-add-submit"
                                />
                            }
                        >
                            Add
                        </TooltipTrigger>
                        {disabledReason && <TooltipContent>{disabledReason}</TooltipContent>}
                    </Tooltip>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

function AddAccessPicker({
    id,
    placeholder,
    emptyText,
    optionsByKey,
    disabled,
}: {
    id: string
    placeholder: string
    emptyText: string
    optionsByKey: Record<string, AddAccessOption>
    disabled: boolean
}): JSX.Element {
    const anchor = useComboboxAnchor()

    return (
        <>
            <ComboboxChips ref={anchor}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((key) => (
                                <ComboboxChip key={key} title={optionsByKey[key]?.name}>
                                    <span className="ph-no-capture">{optionsByKey[key]?.name ?? key}</span>
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                id={id}
                                placeholder={values.length ? '' : placeholder}
                                disabled={disabled}
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>{emptyText}</ComboboxEmpty>
                <ComboboxList>
                    {(key: string) => {
                        const option = optionsByKey[key]
                        return (
                            <ComboboxItem key={key} value={key}>
                                <span className="ph-no-capture flex min-w-0 items-center gap-2">
                                    {option?.email !== undefined && (
                                        <QuillPersonAvatar name={option.name} email={option.email} size="xs" />
                                    )}
                                    <span className="truncate">{option?.name ?? key}</span>
                                    {option?.email && (
                                        <Text size="xs" variant="muted" render={<span className="truncate" />}>
                                            {option.email}
                                        </Text>
                                    )}
                                </span>
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}
