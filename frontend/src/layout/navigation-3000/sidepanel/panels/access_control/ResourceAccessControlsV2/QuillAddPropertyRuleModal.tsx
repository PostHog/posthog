import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
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
    Item,
    ItemContent,
    ItemDescription,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { AccessLevelEnumApi } from 'products/access_control/frontend/generated/api.schemas'

import { addPropertyRestrictionModalLogic } from './addPropertyRestrictionModalLogic'
import { PROPERTY_RULE_LEVEL_OPTIONS } from './helpers'
import { QuillLevelSelect } from './QuillLevelSelect'
import type { ScopeType } from './types'

type PropertyType = 'person' | 'event' | 'ai'

const PROPERTY_TYPE_ITEMS: { value: PropertyType; label: string }[] = [
    { value: 'person', label: 'Person property' },
    { value: 'event', label: 'Event property' },
    { value: 'ai', label: 'ai_events property' },
]

function propertyLevelLabel(level: AccessLevelEnumApi): string {
    return PROPERTY_RULE_LEVEL_OPTIONS.find((o) => o.value === level)?.label ?? level
}

export function QuillAddPropertyRuleModal({
    projectId,
    scopeType,
    subjectId,
}: {
    projectId: string
    scopeType: ScopeType
    subjectId: string
}): JSX.Element {
    const logic = addPropertyRestrictionModalLogic({ projectId, scopeType, subjectId })
    const {
        isOpen,
        propertyType,
        propertyId,
        level,
        displayPropertyOptions,
        propertyOptionsLoading,
        existingRule,
        ruleSaving,
    } = useValues(logic)
    const { closeModal, setPropertyType, setSearch, setPropertyId, setLevel, submitRule } = useActions(logic)
    const id = useId()

    const savingReason = ruleSaving ? 'Saving…' : undefined
    const propertyNames = new Map(displayPropertyOptions.map((o) => [o.id, o.name]))

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open) => {
                if (!open && !ruleSaving) {
                    closeModal()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Add property rule</DialogTitle>
                    <DialogDescription>
                        {scopeType === 'default'
                            ? "Set everyone's access to a specific property."
                            : `Set this ${scopeType === 'role' ? 'role' : 'member'}'s access to a specific property.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor={`${id}-type`}>Type</FieldLabel>
                            <Select
                                items={PROPERTY_TYPE_ITEMS}
                                value={propertyType}
                                onValueChange={(next) => next && setPropertyType(next as PropertyType)}
                            >
                                <SelectTrigger
                                    id={`${id}-type`}
                                    className="w-full"
                                    disabledReason={savingReason}
                                    data-attr="property-rule-type"
                                >
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {PROPERTY_TYPE_ITEMS.map((item) => (
                                        <SelectItem key={item.value} value={item.value}>
                                            {item.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={`${id}-property`}>Property</FieldLabel>
                            <Combobox
                                items={displayPropertyOptions.map((o) => o.id)}
                                value={propertyId}
                                onValueChange={(next: string | null) => setPropertyId(next ?? null)}
                                onInputValueChange={(search: string, { reason }) => {
                                    if (reason === 'input-change' || reason === 'input-clear') {
                                        setSearch(search)
                                    }
                                }}
                                itemToStringLabel={(propertyKey: string) =>
                                    propertyNames.get(propertyKey) ?? propertyKey
                                }
                            >
                                <ComboboxInput
                                    id={`${id}-property`}
                                    placeholder="Search by name…"
                                    disabledReason={savingReason}
                                    data-attr="property-rule-property"
                                />
                                <ComboboxContent>
                                    <ComboboxEmpty>{propertyOptionsLoading ? 'Loading…' : 'No matches'}</ComboboxEmpty>
                                    <ComboboxList>
                                        {(propertyKey: string) => (
                                            <ComboboxItem key={propertyKey} value={propertyKey}>
                                                <span className="truncate">{propertyNames.get(propertyKey)}</span>
                                            </ComboboxItem>
                                        )}
                                    </ComboboxList>
                                </ComboboxContent>
                            </Combobox>
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={`${id}-level`}>Access</FieldLabel>
                            <QuillLevelSelect
                                id={`${id}-level`}
                                value={level}
                                options={PROPERTY_RULE_LEVEL_OPTIONS}
                                onChange={(newLevel) => newLevel && setLevel(newLevel)}
                                disabledReason={savingReason}
                                className="w-full"
                            />
                        </Field>
                        {existingRule ? (
                            <Item tone="warning" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        {`"${existingRule.property}" already has a rule. ${
                                            existingRule.access_level === level
                                                ? `It's already set to ${propertyLevelLabel(level)}.`
                                                : `Saving updates it from ${propertyLevelLabel(
                                                      existingRule.access_level
                                                  )} to ${propertyLevelLabel(level)}.`
                                        }`}
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : null}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeModal} disabledReason={savingReason}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        disabledReason={
                            propertyOptionsLoading
                                ? 'Loading properties'
                                : !propertyId
                                  ? 'Select a property'
                                  : existingRule?.access_level === level
                                    ? 'The rule already has this level'
                                    : undefined
                        }
                        loading={ruleSaving}
                        onClick={submitRule}
                    >
                        {existingRule ? 'Update rule' : 'Add rule'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
