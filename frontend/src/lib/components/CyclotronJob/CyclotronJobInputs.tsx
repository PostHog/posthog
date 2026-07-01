import { DndContext, closestCenter } from '@dnd-kit/core'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'

import {
    IconBrackets,
    IconGear,
    IconLock,
    IconPlus,
    IconToggleOff,
    IconTrash,
    IconWarning,
    IconX,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdown'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { uuid } from 'lib/utils/dom'
import { objectsEqual } from 'lib/utils/objects'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { CyclotronJobInputSchemaType, CyclotronJobInputType, CyclotronJobInvocationGlobalsWithInputs } from '~/types'

import { EmailTemplater } from '../../../scenes/hog-functions/email-templater/EmailTemplater'
import { CUSTOM_INPUT_RENDERERS } from './customInputRenderers'
import { cyclotronJobInputLogic, formatJsonValue } from './cyclotronJobInputLogic'
import { CyclotronJobTemplateSuggestionsButton } from './CyclotronJobTemplateSuggestions'
import { CyclotronJobInputIntegration } from './integrations/CyclotronJobInputIntegration'
import { CyclotronJobInputIntegrationField } from './integrations/CyclotronJobInputIntegrationField'
import { CyclotronJobInputConfiguration } from './types'

export const EXTEND_OBJECT_KEY = '$$_extend_object'

// Template inputs are edited as strings, but API/MCP callers can save non-string values
// (e.g. a raw boolean in a dictionary input) — Monaco throws if given a non-string value.
export function coerceTemplateValueForDisplay(value: unknown, templating: 'hog' | 'liquid' | false): string {
    if (typeof value === 'string') {
        return value
    }
    if (value === null || value === undefined) {
        return ''
    }
    if (templating === 'hog' && (typeof value === 'boolean' || typeof value === 'number')) {
        // A single-expression hog template evaluates to the raw value, so the runtime type is
        // preserved if the user edits and saves this representation
        return `{${JSON.stringify(value)}}`
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}

const INPUT_TYPE_LIST = [
    'string',
    'number',
    'boolean',
    'dictionary',
    'choice',
    'json',
    'integration',
    'email',
    'native_email',
    'non_failure_status_codes',
] as const

// Keyed by the full CyclotronJobInputSchemaType['type'] union — the schema editor's LemonSelect
// receives `value={value.type}` which widens the inferred T past INPUT_TYPE_LIST, so the map's
// indexer needs to accept any of the schema types.
const INPUT_TYPE_LABELS: Partial<Record<CyclotronJobInputSchemaType['type'], string>> = {
    native_email: 'Native email',
    non_failure_status_codes: 'Non-failure codes',
}

const INPUT_TYPE_DEFAULT_DESCRIPTIONS: Partial<Record<CyclotronJobInputSchemaType['type'], string>> = {
    non_failure_status_codes:
        'HTTP response codes that should NOT mark the invocation as failed. Accepts specific codes (e.g. 409, 422) or the wildcards 4xx and 5xx. Useful when an API returns 4xx for expected non-error states.',
}

const NON_FAILURE_STATUS_CODE_SUGGESTIONS = ['4xx', '5xx', '400', '401', '403', '404', '409', '422', '429']

function isValidNonFailureStatusCode(entry: string): boolean {
    if (/^[4-5]xx$/i.test(entry)) {
        return true
    }
    const n = Number(entry)
    return Number.isInteger(n) && n >= 400 && n <= 599
}

export type CyclotronJobInputsProps = {
    onInputChange?: (key: string, input: CyclotronJobInputType) => void
    configuration: CyclotronJobInputConfiguration
    errors?: Record<string, string>
    warnings?: Record<string, string>
    parentConfiguration?: CyclotronJobInputConfiguration
    onInputSchemaChange?: (schema: CyclotronJobInputSchemaType[]) => void
    showSource: boolean
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}

export function CyclotronJobInputs({
    configuration,
    parentConfiguration,
    onInputSchemaChange,
    onInputChange,
    errors,
    warnings,
    showSource,
    sampleGlobalsWithInputs,
}: CyclotronJobInputsProps): JSX.Element | null {
    if (!configuration.inputs_schema?.length) {
        return <span className="italic text-secondary">This function does not require any input variables.</span>
    }

    const inputSchemas = configuration.inputs_schema
    const inputSchemaIds = inputSchemas.map((schema: CyclotronJobInputSchemaType) => schema.key)

    return (
        <>
            <DndContext
                collisionDetection={closestCenter}
                onDragEnd={({ active, over }) => {
                    if (over && active.id !== over.id) {
                        const oldIndex = inputSchemaIds.indexOf(active.id as string)
                        const newIndex = inputSchemaIds.indexOf(over.id as string)

                        onInputSchemaChange?.(arrayMove(inputSchemas, oldIndex, newIndex))
                    }
                }}
            >
                <SortableContext disabled={!showSource} items={inputSchemaIds} strategy={verticalListSortingStrategy}>
                    {configuration.inputs_schema
                        ?.filter((i: CyclotronJobInputSchemaType) => !i.hidden)
                        .map((schema: CyclotronJobInputSchemaType) => {
                            return (
                                <CyclotronJobInputWithSchema
                                    key={schema.key}
                                    schema={schema}
                                    configuration={configuration}
                                    parentConfiguration={parentConfiguration}
                                    onInputSchemaChange={onInputSchemaChange}
                                    onInputChange={onInputChange}
                                    showSource={showSource}
                                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                                    errors={errors}
                                    warnings={warnings}
                                />
                            )
                        })}
                </SortableContext>
            </DndContext>
        </>
    )
}

function JsonConfigField(props: {
    input: CyclotronJobInputType
    onChange?: (input: CyclotronJobInputType) => void
    className?: string
    autoFocus?: boolean
    templating?: boolean
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}): JSX.Element {
    const key = useMemo(() => `json_field_${uuid()}`, [])
    const templatingKind = props.input.templating ?? 'hog'
    const [isExpanded, setIsExpanded] = useState(true)

    // Set up validation logic for this JSON field
    const logic = cyclotronJobInputLogic({
        fieldKey: key,
        initialValue: props.input.value,
        onChange: (value) => props.onChange?.({ ...props.input, value }),
    })

    const { error, jsonValue } = useValues(logic)
    const { setJsonValue } = useActions(logic)

    // Format initial value for display
    const formattedValue = useMemo(() => formatJsonValue(props.input.value), [props.input.value])

    const panels = [
        {
            key: 1,
            header: isExpanded ? 'Click to collapse' : 'Click to expand',
            content: (
                <LemonField.Pure error={error}>
                    <span className={clsx('group relative', props.className)}>
                        <CodeEditorResizeable
                            language={props.templating ? (templatingKind === 'hog' ? 'hogJson' : 'liquid') : 'json'}
                            value={formattedValue}
                            embedded={true}
                            onChange={(value) => setJsonValue(value || '{}')}
                            options={{
                                lineNumbers: 'off',
                                minimap: {
                                    enabled: false,
                                },
                                scrollbar: {
                                    vertical: 'hidden',
                                    verticalScrollbarSize: 0,
                                    alwaysConsumeMouseWheel: false,
                                },
                            }}
                            globals={props.templating ? (props.sampleGlobalsWithInputs ?? undefined) : undefined}
                        />
                        {props.templating ? (
                            <span className="absolute top-0 right-0 z-10 p-px opacity-0 transition-opacity group-hover:opacity-100">
                                <CyclotronJobTemplateSuggestionsButton
                                    templating={templatingKind}
                                    value={jsonValue}
                                    setTemplatingEngine={(templating) =>
                                        props.onChange?.({ ...props.input, templating })
                                    }
                                    onOptionSelect={(option) => {
                                        void copyToClipboard(`{${option.example}}`, 'template code')
                                    }}
                                />
                            </span>
                        ) : null}
                    </span>
                </LemonField.Pure>
            ),
            className: 'p-0',
        },
    ]

    return (
        <LemonCollapse
            embedded={false}
            panels={panels}
            size="xsmall"
            activeKey={isExpanded ? 1 : undefined}
            onChange={(key) => setIsExpanded(key === 1)}
        />
    )
}

function EmailTemplateField({
    schema,
    value,
    onChange,
    sampleGlobalsWithInputs,
}: {
    schema: CyclotronJobInputSchemaType
    value: any
    onChange: (value: any) => void
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}): JSX.Element {
    return (
        <EmailTemplater
            type={schema.type as 'email' | 'native_email'}
            variables={sampleGlobalsWithInputs ?? {}}
            defaultValue={schema.default}
            value={value}
            onChange={onChange}
            templating={schema.templating}
        />
    )
}

function CyclotronJobTemplateInput(props: {
    className?: string
    templating: boolean
    onChange?: (value: CyclotronJobInputType) => void
    input: CyclotronJobInputType
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
    placeholder?: string
}): JSX.Element {
    const templating = props.input.templating ?? 'hog'
    const displayValue = coerceTemplateValueForDisplay(props.input.value, props.templating ? templating : false)

    if (!props.templating) {
        return (
            <LemonInput
                type="text"
                className={props.className}
                value={displayValue}
                onChange={(val) => props.onChange?.({ ...props.input, value: val })}
                placeholder={props.placeholder}
            />
        )
    }

    return (
        <span className={clsx('group relative', props.className)}>
            <CodeEditorInline
                minHeight="37" // Match other inputs
                value={displayValue}
                onChange={(val) => props.onChange?.({ ...props.input, value: val ?? '' })}
                language={props.input.templating === 'hog' ? 'hogTemplate' : 'liquid'}
                globals={props.sampleGlobalsWithInputs ?? undefined}
            />
            <span className="absolute top-0 right-0 z-10 p-px opacity-0 transition-opacity group-hover:opacity-100">
                <CyclotronJobTemplateSuggestionsButton
                    templating={templating}
                    value={displayValue}
                    setTemplatingEngine={(templating) => props.onChange?.({ ...props.input, templating })}
                    onOptionSelect={(option) => {
                        props.onChange?.({ ...props.input, value: `${displayValue} {${option.example}}` })
                    }}
                />
            </span>
        </span>
    )
}

function DictionaryField({
    input,
    onChange,
    templating,
    sampleGlobalsWithInputs,
}: {
    input: CyclotronJobInputType
    onChange?: (value: CyclotronJobInputType) => void
    templating: boolean
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}): JSX.Element {
    const value = input.value ?? {}
    const [entries, setEntries] = useState<[string, any][]>(() => Object.entries(value))
    const prevFilteredEntriesRef = useRef<[string, any][]>(entries)

    useEffect(() => {
        // NOTE: Filter out all empty entries as fetch will throw if passed in
        const filteredEntries = entries.filter(
            ([key, val]) => key.trim() !== '' || typeof val !== 'string' || val.trim() !== ''
        )

        // Compare with previous filtered entries to avoid unnecessary updates
        if (objectsEqual(filteredEntries, prevFilteredEntriesRef.current)) {
            return
        }

        // Update the ref with current filtered entries
        prevFilteredEntriesRef.current = filteredEntries

        const val = Object.fromEntries(filteredEntries)
        onChange?.({ ...input, value: val }) // oxlint-disable-line react-hooks/exhaustive-deps
    }, [entries, onChange])

    const handleEnableIncludeObject = (): void => {
        setEntries((prev) => [[EXTEND_OBJECT_KEY, '{event.properties}'], ...prev])
    }

    return (
        <div className="deprecated-space-y-2">
            {templating && !entries.some(([key]) => key === EXTEND_OBJECT_KEY) ? (
                <LemonButton icon={<IconPlus />} size="small" type="secondary" onClick={handleEnableIncludeObject}>
                    Include properties from an entire object
                </LemonButton>
            ) : null}
            {entries.map(([key, val], index) => (
                <div className="flex gap-2 items-center" key={index}>
                    <Tooltip title={EXTEND_OBJECT_KEY === key ? 'Include properties from an entire object' : undefined}>
                        <LemonInput
                            value={key === EXTEND_OBJECT_KEY ? 'INCLUDE ENTIRE OBJECT' : key}
                            disabled={key === EXTEND_OBJECT_KEY}
                            className="flex-1 min-w-60"
                            onChange={(key) => {
                                setEntries((prev) => {
                                    const newEntries = [...prev]
                                    newEntries[index] = [key, newEntries[index][1]]
                                    return newEntries
                                })
                            }}
                            placeholder="Key"
                        />
                    </Tooltip>

                    <CyclotronJobTemplateInput
                        className="overflow-hidden flex-2"
                        placeholder="Value"
                        input={{ ...input, value: val }}
                        onChange={(val) => {
                            if (val.templating) {
                                onChange?.({ ...input, templating: val.templating })
                            }

                            setEntries((prev) => {
                                const newEntries = [...prev]
                                newEntries[index] = [newEntries[index][0], val.value ?? '']
                                return newEntries
                            })
                        }}
                        templating={templating}
                        sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                    />

                    <LemonButton
                        icon={<IconX />}
                        size="small"
                        onClick={() => {
                            setEntries((prev) => {
                                const newEntries = [...prev]
                                newEntries.splice(index, 1)
                                return newEntries
                            })
                        }}
                    />
                </div>
            ))}
            <LemonButton
                icon={<IconPlus />}
                size="small"
                type="secondary"
                onClick={() => {
                    setEntries((prev) => [...prev, ['', '']])
                }}
            >
                Add entry
            </LemonButton>
        </div>
    )
}

function BooleanField({
    input,
    onChange,
    disabled,
    templating,
    sampleGlobalsWithInputs,
}: {
    input: CyclotronJobInputType
    onChange?: (value: CyclotronJobInputType) => void
    disabled?: boolean
    templating: boolean
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}): JSX.Element {
    const isTemplateMode = typeof input.value === 'string'

    if (isTemplateMode) {
        // Boolean fields only support Hog templating - Liquid renders as strings
        // which bypasses boolean type guarantees
        const hogInput = input.templating === 'liquid' ? { ...input, templating: 'hog' as const } : input
        return (
            <CyclotronJobTemplateInput
                input={hogInput}
                onChange={(val) => onChange?.({ ...val, templating: 'hog' })}
                templating={templating}
                sampleGlobalsWithInputs={sampleGlobalsWithInputs}
            />
        )
    }

    return (
        <LemonSwitch
            checked={!!input.value}
            onChange={(checked) => onChange?.({ ...input, value: checked })}
            disabled={disabled}
        />
    )
}

type SearchableChoice = { value: any; label: string }

function SearchableChoiceCombobox({
    value,
    onChange,
    choices,
    disabled,
}: {
    value: any
    onChange: (value: any) => void
    choices: SearchableChoice[]
    disabled?: boolean
}): JSX.Element {
    // Mirrors quill's `InputInsidePopup` combobox story: LemonButton as the trigger,
    // ComboboxInput rendered inside ComboboxContent so the search field stays visible on
    // open. Combobox primitive auto-scrolls the active item into view but the input lives
    // outside the scrolling list, so it doesn't get pushed offscreen.
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const selectedLabel = choices.find((choice) => choice.value === value)?.label ?? null

    return (
        <Combobox
            items={choices}
            itemToStringValue={(choice: SearchableChoice) => choice.label}
            open={open}
            onOpenChange={setOpen}
            value={choices.find((choice) => choice.value === value) ?? null}
            onValueChange={(choice: SearchableChoice | null) => onChange(choice ? choice.value : null)}
        >
            <LemonButton
                ref={triggerRef}
                type="secondary"
                fullWidth
                disabled={disabled}
                onClick={() => setOpen((prev) => !prev)}
                className="ph-no-capture"
            >
                {selectedLabel ?? <span className="text-secondary">Select a value</span>}
            </LemonButton>
            <ComboboxContent anchor={triggerRef}>
                <ComboboxInput placeholder="Search" showTrigger={false} />
                <ComboboxEmpty>No items found</ComboboxEmpty>
                <ComboboxList>
                    {(choice: SearchableChoice) => (
                        <ComboboxItem key={String(choice.value)} value={choice}>
                            {choice.label}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

type CyclotronJobInputProps = {
    schema: CyclotronJobInputSchemaType
    input: CyclotronJobInputType
    onChange?: (value: CyclotronJobInputType) => void
    onInputChange?: (key: string, input: CyclotronJobInputType) => void
    disabled?: boolean
    configuration: CyclotronJobInputConfiguration
    parentConfiguration?: CyclotronJobInputConfiguration
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}

function NonFailureStatusCodesField({
    value,
    onChange,
    disabled,
}: {
    value: unknown
    onChange: (value: Array<number | string>) => void
    disabled?: boolean
}): JSX.Element {
    const current: string[] = Array.isArray(value) ? value.map((v) => String(v)) : []
    const invalid = current.filter((v) => !isValidNonFailureStatusCode(v))

    return (
        <div className="deprecated-space-y-1">
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={current}
                onChange={(next) => {
                    const normalized: Array<number | string> = next.map((entry) => {
                        const trimmed = entry.trim()
                        const n = Number(trimmed)
                        return /^[1-5]xx$/i.test(trimmed) ? trimmed.toLowerCase() : Number.isInteger(n) ? n : trimmed
                    })
                    onChange(normalized)
                }}
                options={NON_FAILURE_STATUS_CODE_SUGGESTIONS.map((v) => ({ key: v, label: v }))}
                placeholder="e.g. 4xx, 400, 429"
                disabled={disabled}
            />
            {invalid.length > 0 && (
                <div className="text-xs text-danger">
                    Invalid {invalid.length === 1 ? 'entry' : 'entries'}: {invalid.join(', ')}. Use a number between 400
                    and 599, <code>4xx</code>, or <code>5xx</code>.
                </div>
            )}
        </div>
    )
}

function CyclotronJobInputRenderer({
    onChange,
    onInputChange,
    schema,
    disabled,
    input,
    configuration,
    parentConfiguration,
    sampleGlobalsWithInputs,
}: CyclotronJobInputProps): JSX.Element {
    const templating = schema.templating ?? true

    const onValueChange = (value: any): void => onChange?.({ ...input, value })
    switch (schema.type) {
        case 'string':
            return (
                <CyclotronJobTemplateInput
                    input={input}
                    onChange={disabled ? () => {} : onChange}
                    className="ph-no-capture"
                    templating={templating}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
            )
        case 'number':
            return <LemonInput type="number" value={input.value} onChange={onValueChange} className="ph-no-capture" />
        case 'json':
            return (
                <JsonConfigField
                    input={input}
                    onChange={onChange}
                    className="ph-no-capture"
                    templating={templating}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
            )
        case 'choice':
            if (schema.searchable) {
                return (
                    <SearchableChoiceCombobox
                        value={input.value}
                        onChange={onValueChange}
                        choices={schema.choices ?? []}
                        disabled={disabled}
                    />
                )
            }
            return (
                <LemonSelect
                    fullWidth
                    value={input.value}
                    className="ph-no-capture"
                    onChange={onValueChange}
                    options={schema.choices ?? []}
                    disabled={disabled}
                />
            )
        case 'dictionary':
            return (
                <DictionaryField
                    input={input}
                    onChange={onChange}
                    templating={templating}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
            )
        case 'boolean':
            return (
                <BooleanField
                    input={input}
                    onChange={onChange}
                    disabled={disabled}
                    templating={templating}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
            )
        case 'integration':
            return (
                <CyclotronJobInputIntegration
                    schema={schema}
                    value={input.value}
                    onChange={(newValue) => {
                        // Clear all integration_field inputs when the integration changes
                        if (configuration.inputs_schema && onInputChange) {
                            configuration.inputs_schema
                                .filter((s: CyclotronJobInputSchemaType) => s.type === 'integration_field')
                                .forEach((field: CyclotronJobInputSchemaType) => {
                                    onInputChange(field.key, { value: null })
                                })
                        }

                        onValueChange(newValue)
                    }}
                />
            )
        case 'integration_field':
            return (
                <CyclotronJobInputIntegrationField
                    schema={schema}
                    value={input.value}
                    onChange={onValueChange}
                    parentConfiguration={parentConfiguration}
                    configuration={configuration}
                />
            )
        case 'email':
        case 'native_email':
            return (
                <EmailTemplateField
                    schema={schema}
                    value={input.value}
                    onChange={onValueChange}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
            )
        case 'non_failure_status_codes':
            return <NonFailureStatusCodesField value={input.value} onChange={onValueChange} disabled={disabled} />
        default: {
            const CustomRenderer = CUSTOM_INPUT_RENDERERS[schema.type]
            if (CustomRenderer) {
                return (
                    <Suspense>
                        <CustomRenderer
                            schema={schema}
                            value={input.value}
                            onChange={onValueChange}
                            sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                        />
                    </Suspense>
                )
            }
            return (
                <strong className="text-danger">
                    Unknown field type "<code>{schema.type}</code>".
                </strong>
            )
        }
    }
}

type CyclotronJobInputSchemaControlsProps = {
    value: CyclotronJobInputSchemaType
    onChange: (value: CyclotronJobInputSchemaType | null) => void
    onDone: () => void
    configuration: CyclotronJobInputConfiguration
    parentConfiguration?: CyclotronJobInputConfiguration
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}

function CyclotronJobInputSchemaControls({
    value,
    onChange,
    onDone,
    configuration,
    parentConfiguration,
    sampleGlobalsWithInputs,
}: CyclotronJobInputSchemaControlsProps): JSX.Element {
    const _onChange = (data: Partial<CyclotronJobInputSchemaType> | null): void => {
        if (data?.key?.length === 0) {
            setLocalVariableError('Input variable name cannot be empty')
            return
        }
        onChange(data ? { ...value, ...data } : null)
    }

    const [localVariableValue, setLocalVariableValue] = useState(value.key)
    const [localVariableError, setLocalVariableError] = useState<string | null>(null)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap flex-1 gap-2 items-center">
                <LemonSelect
                    size="small"
                    options={INPUT_TYPE_LIST.map((type) => ({
                        label: INPUT_TYPE_LABELS[type] ?? capitalizeFirstLetter(type),
                        value: type,
                    }))}
                    value={value.type}
                    className="min-w-40"
                    onChange={(type) => {
                        const defaultDescription = INPUT_TYPE_DEFAULT_DESCRIPTIONS[type]
                        // Seed the description from the type's default if the author hasn't written one
                        if (defaultDescription && !value.description) {
                            _onChange({ type, description: defaultDescription })
                        } else {
                            _onChange({ type })
                        }
                    }}
                />
                <LemonCheckbox
                    size="small"
                    checked={value.required}
                    onChange={(required) => _onChange({ required })}
                    label="Required"
                    bordered
                />
                <LemonCheckbox
                    size="small"
                    checked={value.secret}
                    onChange={(secret) => _onChange({ secret })}
                    label="Secret"
                    bordered
                />
                <div className="flex-1" />
                <LemonButton status="danger" icon={<IconTrash />} size="small" onClick={() => onChange(null)} />
                <LemonButton type="secondary" size="small" onClick={() => onDone()}>
                    Done
                </LemonButton>
            </div>
            <div className="flex flex-wrap flex-1 gap-2">
                <LemonField.Pure label="Display label">
                    <LemonInput
                        className="min-w-60"
                        size="small"
                        value={value.label}
                        onChange={(label) => _onChange({ label })}
                        placeholder="Display label"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Input variable name" error={localVariableError}>
                    <LemonInput
                        size="small"
                        value={localVariableValue}
                        // Special case - the component is keyed by this so the whole thing will re-mount on changes
                        // so we defer the change to blur
                        onChange={(key) => setLocalVariableValue(key)}
                        onBlur={() => _onChange({ key: localVariableValue })}
                        placeholder="Variable name"
                    />
                </LemonField.Pure>
            </div>

            <LemonField.Pure label="Description">
                <LemonTextArea
                    minRows={1}
                    value={value.description}
                    onChange={(description) => _onChange({ description })}
                    placeholder="Description"
                />
            </LemonField.Pure>
            {value.type === 'choice' && (
                <LemonField.Pure label="Choices">
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={value.choices?.map((choice) => choice.value)}
                        onChange={(choices) =>
                            _onChange({ choices: choices.map((value) => ({ label: value, value })) })
                        }
                        placeholder="Choices"
                    />
                </LemonField.Pure>
            )}

            {value.type === 'integration' && (
                <LemonField.Pure label="Integration kind">
                    <LemonSelect
                        value={value.integration}
                        onChange={(integration) => _onChange({ integration })}
                        options={[
                            { label: 'Slack', value: 'slack' },
                            { label: 'Salesforce', value: 'salesforce' },
                            { label: 'Hubspot', value: 'hubspot' },
                        ]}
                        placeholder="Choose kind"
                    />
                </LemonField.Pure>
            )}

            <LemonField.Pure label="Default value">
                <CyclotronJobInputRenderer
                    schema={value}
                    input={{ value: value.default }}
                    onChange={(val) => _onChange({ default: val.value })}
                    configuration={configuration}
                    parentConfiguration={parentConfiguration}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
            </LemonField.Pure>
        </div>
    )
}

type CyclotronJobInputWithSchemaProps = CyclotronJobInputsProps & {
    schema: CyclotronJobInputSchemaType
    sampleGlobalsWithInputs: CyclotronJobInvocationGlobalsWithInputs | null
}

function CyclotronJobInputWithSchema({
    schema,
    configuration,
    parentConfiguration,
    onInputSchemaChange,
    onInputChange,
    showSource,
    sampleGlobalsWithInputs,
    errors,
    warnings,
}: CyclotronJobInputWithSchemaProps): JSX.Element | null {
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: schema.key })
    const [editing, setEditing] = useState(false)
    const value = configuration.inputs?.[schema.key] ?? { value: null }
    const error = errors?.[schema.key]
    const warning = warnings?.[schema.key]

    const onSchemaChange = (newSchema: CyclotronJobInputSchemaType | null): void => {
        let inputsSchema = configuration.inputs_schema || []
        if (!newSchema) {
            inputsSchema = inputsSchema.filter((s: CyclotronJobInputSchemaType) => s.key !== schema.key)
        } else {
            const modifiedSchema = { ...schema, ...newSchema }
            inputsSchema = inputsSchema.map((s: CyclotronJobInputSchemaType) =>
                s.key === schema.key ? modifiedSchema : s
            )
        }

        if (newSchema?.key) {
            onInputChange?.(newSchema.key, value)
        }

        const isEmptyValue = (v: unknown): boolean =>
            v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)

        if (newSchema?.type && newSchema.type !== schema.type) {
            // Reset on type change; seed from schema default when one is declared
            onInputChange?.(schema.key, {
                value: newSchema.default !== undefined ? newSchema.default : null,
            })
        } else if (newSchema?.default !== undefined && isEmptyValue(value.value)) {
            // Seed an empty input value from the schema's default so save succeeds without a separate edit
            onInputChange?.(newSchema.key ?? schema.key, { ...value, value: newSchema.default })
        }
        onInputSchemaChange?.(inputsSchema)
    }

    useEffect(() => {
        if (!showSource) {
            setEditing(false)
        }
    }, [showSource])

    const onChange = (newValue: CyclotronJobInputType): void => {
        onInputChange?.(schema.key, {
            // Keep the existing parts if they exist
            ...value,
            ...newValue,
        })
    }

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
        >
            {!editing ? (
                <LemonField.Pure
                    error={error}
                    help={
                        typeof schema.description === 'string' ? (
                            <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings>
                                {schema.description}
                            </LemonMarkdown>
                        ) : undefined
                    }
                >
                    <>
                        <div className="flex gap-2 items-center">
                            <LemonLabel
                                className={showSource ? 'cursor-grab' : ''}
                                showOptional={!schema.required}
                                {...attributes}
                                {...listeners}
                            >
                                {schema.label || schema.key}
                                {schema.secret ? (
                                    <Tooltip title="This input is marked as secret. It will be encrypted and not visible after saving.">
                                        <IconLock />
                                    </Tooltip>
                                ) : undefined}
                            </LemonLabel>
                            {schema.type === 'boolean' && (schema.templating ?? true) && (
                                <LemonSelect
                                    size="xsmall"
                                    type="tertiary"
                                    value={typeof value?.value === 'string' ? 'conditional' : 'toggle'}
                                    options={[
                                        { value: 'toggle', label: 'Toggle', icon: <IconToggleOff /> },
                                        { value: 'conditional', label: 'Conditional', icon: <IconBrackets /> },
                                    ]}
                                    onChange={(mode) => {
                                        if (mode === 'toggle') {
                                            onChange({ ...value, value: false })
                                        } else {
                                            onChange({
                                                ...value,
                                                value: `{event.property.foo = 'bar'}`,
                                                templating: 'hog',
                                            })
                                        }
                                    }}
                                />
                            )}
                            {showSource && (
                                <LemonTag type="muted" className="font-mono">
                                    inputs.{schema.key}
                                </LemonTag>
                            )}
                            <div className="flex-1" />

                            {showSource && (
                                <LemonButton
                                    size="small"
                                    noPadding
                                    icon={<IconGear />}
                                    onClick={() => setEditing(true)}
                                />
                            )}
                        </div>
                        {value?.secret ? (
                            <div className="flex gap-2 items-center p-1 rounded border border-dashed">
                                <span className="flex-1 p-1 italic text-secondary">
                                    This value is secret and is not displayed here.
                                </span>
                                <LemonButton
                                    onClick={() => {
                                        onChange({ value: '', secret: false })
                                    }}
                                    size="small"
                                    type="secondary"
                                >
                                    Edit
                                </LemonButton>
                            </div>
                        ) : (
                            <CyclotronJobInputRenderer
                                schema={schema}
                                input={value ?? { value: '' }}
                                onChange={onChange}
                                onInputChange={onInputChange}
                                configuration={configuration}
                                parentConfiguration={parentConfiguration}
                                sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                            />
                        )}
                        {warning && !value?.secret ? (
                            <div className="flex gap-1 items-start mt-1 text-xs text-warning">
                                <IconWarning className="mt-0.5 shrink-0 text-base" />
                                <span>{warning}</span>
                            </div>
                        ) : null}
                    </>
                </LemonField.Pure>
            ) : (
                <div className="p-2 rounded border border-dashed deprecated-space-y-4">
                    <CyclotronJobInputSchemaControls
                        value={schema}
                        onChange={onSchemaChange}
                        onDone={() => setEditing(false)}
                        configuration={configuration}
                        parentConfiguration={parentConfiguration}
                        sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                    />
                </div>
            )}
        </div>
    )
}
