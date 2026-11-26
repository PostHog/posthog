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

import { toSentenceCase } from 'lib/utils/strings'

import { APIScopeObject } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import { addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'
import { humanizeAccessControlLevel, objectRuleLevelOptions } from './helpers'
import { QuillLevelSelect } from './QuillLevelSelect'
import type { ScopeType } from './types'

export function QuillAddObjectRuleModal({
    projectId,
    scopeType,
    subjectId,
}: {
    projectId: string
    scopeType: ScopeType
    subjectId: string
}): JSX.Element {
    const logic = addObjectOverrideModalLogic({ projectId, scopeType, subjectId })
    const {
        isOpen,
        resource,
        objectId,
        level,
        displayObjectOptions,
        objectOptionsLoading,
        existingRule,
        objectInputKey,
    } = useValues(logic)
    const { objectRuleResourceOptions, availableResourceLevels } = useValues(accessControlsLogic({ projectId }))
    const { closeModal, setResource, setSearch, setObjectId, setLevel, submitRule } = useActions(logic)
    const id = useId()

    const resourceLevels = objectRuleResourceOptions.find((r) => r.resource === resource)
    const typeItems = objectRuleResourceOptions.map((r) => ({
        value: r.resource,
        label: toSentenceCase(r.resource.replace(/_/g, ' ')),
    }))
    const objectNames = new Map(displayObjectOptions.map((o) => [o.id, o.name]))

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && closeModal()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Add access rule</DialogTitle>
                    <DialogDescription>
                        {scopeType === 'default'
                            ? "Grant or restrict everyone's access to a specific object."
                            : `Grant or restrict this ${scopeType === 'role' ? 'role' : 'member'}'s access to a specific object.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel htmlFor={`${id}-type`}>Type</FieldLabel>
                            <Select
                                items={typeItems}
                                value={resource}
                                onValueChange={(next) => next && setResource(next as APIScopeObject)}
                            >
                                <SelectTrigger id={`${id}-type`} className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {typeItems.map((item) => (
                                        <SelectItem key={item.value} value={item.value}>
                                            {item.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={`${id}-object`}>Object</FieldLabel>
                            <Combobox
                                key={objectInputKey}
                                items={displayObjectOptions.map((o) => o.id)}
                                value={objectId}
                                // The backend already searched; filtering again locally would hide its
                                // results whenever the typed text isn't part of the object's name
                                filter={null}
                                onValueChange={(next: string | null) => setObjectId(next ?? null)}
                                onInputValueChange={(search: string, { reason }) => {
                                    if (reason === 'input-change' || reason === 'input-clear') {
                                        setSearch(search)
                                    }
                                }}
                                itemToStringLabel={(objectKey: string) => objectNames.get(objectKey) ?? objectKey}
                            >
                                <ComboboxInput id={`${id}-object`} placeholder="Search by name or paste URL" />
                                <ComboboxContent>
                                    <ComboboxEmpty>{objectOptionsLoading ? 'Loading…' : 'No matches'}</ComboboxEmpty>
                                    <ComboboxList>
                                        {(objectKey: string) => (
                                            <ComboboxItem key={objectKey} value={objectKey}>
                                                <span className="truncate">{objectNames.get(objectKey)}</span>
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
                                options={objectRuleLevelOptions(
                                    resourceLevels?.available_access_levels ?? availableResourceLevels,
                                    resourceLevels?.minimum_access_level
                                )}
                                onChange={(newLevel) => newLevel && setLevel(newLevel)}
                                className="w-full"
                            />
                        </Field>
                        {existingRule ? (
                            <Item tone="warning" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        {`"${existingRule.name}" already has a rule. ${
                                            existingRule.access_level === level
                                                ? `It's already set to ${humanizeAccessControlLevel(level)}.`
                                                : `Saving updates it from ${humanizeAccessControlLevel(
                                                      existingRule.access_level
                                                  )} to ${humanizeAccessControlLevel(level)}.`
                                        }`}
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : null}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeModal}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        disabledReason={
                            !objectId
                                ? 'Select an object'
                                : existingRule?.access_level === level
                                  ? 'The rule already has this level'
                                  : undefined
                        }
                        onClick={submitRule}
                    >
                        {existingRule ? 'Update rule' : 'Add rule'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
