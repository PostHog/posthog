import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'

import { IconRefresh } from '@posthog/icons'
import {
    Badge,
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
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    FieldDescription,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    Textarea,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { urls } from 'scenes/urls'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { DISPLAY_TYPE_OPTIONS } from './customPropertyTypes'

interface ToggleOption {
    value: string
    label: string
    disabledReason?: string
}

function QuillOptionToggleGroup({
    id,
    ariaLabel,
    value,
    options,
    onChange,
}: {
    id: string
    ariaLabel: string
    value: string
    options: ToggleOption[]
    onChange: (value: string) => void
}): JSX.Element {
    return (
        <ToggleGroup
            id={id}
            variant="outline"
            aria-label={ariaLabel}
            value={[value]}
            onValueChange={(next: string[]) => next[0] && onChange(next[0])}
            className="w-full flex-wrap"
        >
            {options.map((option) => (
                <ToggleGroupItem
                    key={option.value}
                    value={option.value}
                    disabledReason={option.disabledReason}
                    className="flex-1"
                >
                    {option.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}

function QuillOptionCombobox({
    id,
    value,
    options,
    placeholder,
    emptyLabel,
    disabledReason,
    onChange,
}: {
    id: string
    value: string | null
    options: { value: string; label: string }[]
    placeholder: string
    emptyLabel: string
    disabledReason?: string
    onChange: (value: string | null) => void
}): JSX.Element {
    const labels = new Map(options.map((option) => [option.value, option.label]))

    return (
        <Combobox
            items={options.map((option) => option.value)}
            value={value}
            onValueChange={onChange}
            itemToStringLabel={(item: string) => labels.get(item) ?? item}
        >
            <ComboboxInput id={id} placeholder={placeholder} disabledReason={disabledReason} />
            <ComboboxContent>
                <ComboboxEmpty>{emptyLabel}</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item}>
                            {labels.get(item) ?? item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

export interface QuillCustomPropertyModalProps {
    submitDisabledReason: string | undefined
    showTargetType: boolean
    targetTypeOptions: ToggleOption[]
    sourceModeOptions: ToggleOption[]
    showBigNumberSwitch: boolean
    hasExistingSource: boolean
    noViews: boolean
    onSavedQueryChange: (newValue: string | null, onChange: (value: string | null) => void) => void
    optionsEditor: JSX.Element
    personSourceEditor: JSX.Element
}

export function QuillCustomPropertyModal({
    submitDisabledReason,
    showTargetType,
    targetTypeOptions,
    sourceModeOptions,
    showBigNumberSwitch,
    hasExistingSource,
    noViews,
    onSavedQueryChange,
    optionsEditor,
    personSourceEditor,
}: QuillCustomPropertyModalProps): JSX.Element {
    const {
        modalVisible,
        editingDefinition,
        customPropertyForm,
        isCustomPropertyFormSubmitting,
        materializedViews,
        selectedSourceColumns,
        savedQueriesLoading,
        definitionsLoading,
        editingHasWorkflowReference,
        editingReferences,
        newWorkflowUrlLoading,
    } = useValues(customPropertyDefinitionsLogic)
    const { closeModal, submitCustomPropertyForm, loadDefinitions, createWorkflowForProperty } =
        useActions(customPropertyDefinitionsLogic)

    const { sourceMode, targetType } = customPropertyForm
    const isProfileTarget = targetType === 'person' || targetType === 'group'
    const viewOptions = materializedViews.map((view) => ({ value: view.id, label: view.name }))
    const columnOptions = selectedSourceColumns.map((column) => ({ value: column, label: column }))
    const columnsDisabledReason = !customPropertyForm.savedQuery ? 'Select a view first' : undefined

    return (
        <Dialog
            open={modalVisible}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeModal()
                }
            }}
        >
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>{editingDefinition ? 'Edit custom property' : 'New custom property'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Form
                        logic={customPropertyDefinitionsLogic}
                        formKey="customPropertyForm"
                        enableFormOnSubmit
                        className="flex flex-col gap-4"
                    >
                        <QuillSettingFormField name="name" label="Name">
                            {({ id, value, onChange, invalid }) => (
                                <Input
                                    id={id}
                                    value={value ?? ''}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder="e.g. ARR"
                                    autoFocus
                                    aria-invalid={invalid || undefined}
                                />
                            )}
                        </QuillSettingFormField>
                        <QuillSettingFormField name="description" label="Description">
                            {({ id, value, onChange, invalid }) => (
                                <Textarea
                                    id={id}
                                    value={value ?? ''}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder="Optional description"
                                    rows={2}
                                    aria-invalid={invalid || undefined}
                                />
                            )}
                        </QuillSettingFormField>
                        {showTargetType && (
                            <QuillSettingFormField name="targetType" label="Attach to">
                                {({ id, value, onChange }) => (
                                    <>
                                        <QuillOptionToggleGroup
                                            id={id}
                                            ariaLabel="Attach to"
                                            value={value}
                                            options={targetTypeOptions}
                                            onChange={onChange}
                                        />
                                        <FieldDescription>
                                            Account properties describe a customer; person properties attach to
                                            individual people and are usable in feature flags, cohorts and insights.
                                        </FieldDescription>
                                    </>
                                )}
                            </QuillSettingFormField>
                        )}
                        {/* Type, big-number and options only drive how an account property is rendered. A
                            person property is a raw $set value, so these are account-only. */}
                        {targetType === 'account' && (
                            <>
                                <QuillSettingFormField name="displayType" label="Type">
                                    {({ id, value, onChange }) => (
                                        <Select items={DISPLAY_TYPE_OPTIONS} value={value} onValueChange={onChange}>
                                            <SelectTrigger id={id} className="w-full">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                {DISPLAY_TYPE_OPTIONS.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>
                                                        {option.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    )}
                                </QuillSettingFormField>
                                {showBigNumberSwitch && (
                                    <KeaField name="isBigNumber" noStyle>
                                        {({ value, onChange }) => (
                                            <QuillSettingSwitch
                                                label="Abbreviate large numbers (e.g. 10,000 → 10K)"
                                                checked={value}
                                                onCheckedChange={onChange}
                                            />
                                        )}
                                    </KeaField>
                                )}
                                {customPropertyForm.displayType === 'select' && optionsEditor}
                            </>
                        )}
                        {isProfileTarget && personSourceEditor}
                        {targetType === 'account' && (
                            <>
                                <QuillSettingFormField name="sourceMode" label="Source">
                                    {({ id, value, onChange }) => (
                                        <QuillOptionToggleGroup
                                            id={id}
                                            ariaLabel="Source"
                                            value={value}
                                            options={sourceModeOptions}
                                            onChange={onChange}
                                        />
                                    )}
                                </QuillSettingFormField>
                                {hasExistingSource && sourceMode !== 'data_warehouse' && (
                                    <Item tone="warning" size="sm">
                                        <ItemContent>
                                            <ItemDescription>
                                                Saving will remove this property's data warehouse sync. Values already
                                                synced will stay, but they'll stop updating automatically.
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                )}
                                {sourceMode === 'data_warehouse' &&
                                    (noViews ? (
                                        <Item tone="info" size="sm">
                                            <ItemContent>
                                                <ItemDescription>
                                                    No materialized views found. Create and materialize a view in the
                                                    data warehouse first, then it can feed this property.
                                                </ItemDescription>
                                            </ItemContent>
                                        </Item>
                                    ) : (
                                        <>
                                            <QuillSettingFormField name="savedQuery" label="View">
                                                {({ id, value, onChange }) => (
                                                    <>
                                                        <QuillOptionCombobox
                                                            id={id}
                                                            value={value}
                                                            options={viewOptions}
                                                            placeholder={
                                                                savedQueriesLoading
                                                                    ? 'Loading views…'
                                                                    : 'Select a materialized view'
                                                            }
                                                            emptyLabel="No matching views"
                                                            disabledReason={
                                                                hasExistingSource
                                                                    ? 'The view is fixed once a sync is created'
                                                                    : undefined
                                                            }
                                                            onChange={(newValue) =>
                                                                onSavedQueryChange(newValue, onChange)
                                                            }
                                                        />
                                                        <FieldDescription>
                                                            Values are pulled from this materialized view on each
                                                            materialization, matched to accounts by external ID.
                                                        </FieldDescription>
                                                    </>
                                                )}
                                            </QuillSettingFormField>
                                            <QuillSettingFormField name="sourceColumn" label="Value column">
                                                {({ id, value, onChange }) => (
                                                    <>
                                                        <QuillOptionCombobox
                                                            id={id}
                                                            value={value}
                                                            options={columnOptions}
                                                            placeholder="Column to read the value from"
                                                            emptyLabel="No matching columns"
                                                            disabledReason={columnsDisabledReason}
                                                            onChange={onChange}
                                                        />
                                                        <FieldDescription>
                                                            The column whose value is written to this property.
                                                        </FieldDescription>
                                                    </>
                                                )}
                                            </QuillSettingFormField>
                                            <QuillSettingFormField name="keyColumn" label="Key column">
                                                {({ id, value, onChange }) => (
                                                    <>
                                                        <QuillOptionCombobox
                                                            id={id}
                                                            value={value}
                                                            options={columnOptions}
                                                            placeholder="Column matching the account external ID"
                                                            emptyLabel="No matching columns"
                                                            disabledReason={columnsDisabledReason}
                                                            onChange={onChange}
                                                        />
                                                        <FieldDescription>
                                                            The column matched against each account's external ID.
                                                        </FieldDescription>
                                                    </>
                                                )}
                                            </QuillSettingFormField>
                                            <KeaField name="isEnabled" noStyle>
                                                {({ value, onChange }) => (
                                                    <QuillSettingSwitch
                                                        label="Sync enabled"
                                                        checked={value}
                                                        onCheckedChange={onChange}
                                                    />
                                                )}
                                            </KeaField>
                                        </>
                                    ))}
                                {sourceMode === 'workflow' &&
                                    (editingReferences.length > 0 ? (
                                        <div className="flex flex-col gap-2">
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                                <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                                                    Workflows updating this property
                                                </Text>
                                                <Button
                                                    size="icon"
                                                    aria-label="Refresh"
                                                    tooltip="Refresh"
                                                    onClick={loadDefinitions}
                                                    loading={definitionsLoading}
                                                >
                                                    <IconRefresh />
                                                </Button>
                                            </div>
                                            <div className="flex flex-col gap-1">
                                                {editingReferences.map((reference) => (
                                                    <Item key={reference.id} variant="outline" size="sm">
                                                        <ItemContent>
                                                            <Button
                                                                variant="link"
                                                                size="sm"
                                                                nativeButton={false}
                                                                className="justify-start"
                                                                render={
                                                                    <LinkPrimitive
                                                                        to={urls.workflow(reference.id, 'workflow')}
                                                                        target="_blank"
                                                                    />
                                                                }
                                                            >
                                                                {reference.name}
                                                            </Button>
                                                        </ItemContent>
                                                        <ItemActions>
                                                            <Badge>{reference.status}</Badge>
                                                        </ItemActions>
                                                    </Item>
                                                ))}
                                            </div>
                                        </div>
                                    ) : editingHasWorkflowReference ? (
                                        <Item tone="warning" size="sm">
                                            <ItemContent>
                                                <ItemDescription>
                                                    You don't have access to view the workflow.
                                                </ItemDescription>
                                            </ItemContent>
                                        </Item>
                                    ) : (
                                        <Empty className="rounded-md border border-border">
                                            <EmptyHeader>
                                                <EmptyDescription>
                                                    No workflows update this property yet. Create one with an "Update
                                                    account property" action that sets this property. The editor opens
                                                    in a new tab. Once you save the workflow there, refresh this list.
                                                </EmptyDescription>
                                            </EmptyHeader>
                                            <EmptyContent>
                                                <Button
                                                    variant="primary"
                                                    onClick={createWorkflowForProperty}
                                                    loading={newWorkflowUrlLoading}
                                                >
                                                    Create workflow
                                                </Button>
                                            </EmptyContent>
                                        </Empty>
                                    ))}
                            </>
                        )}
                    </Form>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeModal}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitCustomPropertyForm}
                        loading={isCustomPropertyFormSubmitting}
                        disabledReason={submitDisabledReason}
                    >
                        {editingDefinition ? 'Save' : 'Create'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
