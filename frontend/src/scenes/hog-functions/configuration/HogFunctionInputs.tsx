import { closestCenter, DndContext } from '@dnd-kit/core'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconGear, IconLock, IconPlus, IconTrash, IconX } from '@posthog/icons'
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
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { capitalizeFirstLetter, objectsEqual } from 'lib/utils'
import { uuid } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    HogFunctionConfigurationType,
    HogFunctionInputSchemaType,
    HogFunctionInputType,
    HogFunctionMappingType,
} from '~/types'

import { EmailTemplater } from '../email-templater/EmailTemplater'
import { HogFunctionInputIntegration } from '../integrations/HogFunctionInputIntegration'
import { HogFunctionInputIntegrationField } from '../integrations/HogFunctionInputIntegrationField'
import { HogFunctionTemplateSuggestionsButton } from './components/HogFunctionTemplateSuggestions'
import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { formatJsonValue, hogFunctionInputLogic } from './HogFunctionInputLogic'

export type HogFunctionInputProps = {
    schema: HogFunctionInputSchemaType
    input: HogFunctionInputType
    onChange?: (value: HogFunctionInputType) => void
    disabled?: boolean
}

export interface HogFunctionInputsProps {
    configuration: HogFunctionConfigurationType | HogFunctionMappingType
    setConfigurationValue: (key: string, value: any) => void
}

export type HogFunctionInputWithSchemaProps = {
    configuration: HogFunctionConfigurationType | HogFunctionMappingType
    setConfigurationValue: (key: string, value: any) => void
    schema: HogFunctionInputSchemaType
}

const typeList = ['string', 'number', 'boolean', 'dictionary', 'choice', 'json', 'integration', 'email'] as const

function JsonConfigField(props: {
    input: HogFunctionInputType
    onChange?: (input: HogFunctionInputType) => void
    className?: string
    autoFocus?: boolean
    templating?: boolean
}): JSX.Element {
    const { sampleGlobalsWithInputs } = useValues(hogFunctionConfigurationLogic)
    const key = useMemo(() => `json_field_${uuid()}`, [])
    const templatingKind = props.input.templating ?? 'hog'

    // Set up validation logic for this JSON field
    const logic = hogFunctionInputLogic({
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
            header: 'Click to edit',
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
                                },
                            }}
                            globals={props.templating ? sampleGlobalsWithInputs : undefined}
                        />
                        {props.templating ? (
                            <span className="absolute top-0 right-0 z-10 p-px opacity-0 transition-opacity group-hover:opacity-100">
                                <HogFunctionTemplateSuggestionsButton
                                    templating={templatingKind}
                                    value={jsonValue}
                                    setTemplating={(templating) => props.onChange?.({ ...props.input, templating })}
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

    return <LemonCollapse embedded={false} panels={panels} size="xsmall" />
}

function EmailTemplateField({
    value,
    onChange,
}: {
    schema: HogFunctionInputSchemaType
    value: any
    onChange: (value: any) => void
}): JSX.Element {
    const { sampleGlobalsWithInputs } = useValues(hogFunctionConfigurationLogic)

    return <EmailTemplater variables={sampleGlobalsWithInputs} value={value} onChange={onChange} />
}

function HogFunctionTemplateInput(props: {
    className?: string
    templating: boolean
    onChange?: (value: HogFunctionInputType) => void
    input: HogFunctionInputType
}): JSX.Element {
    const { sampleGlobalsWithInputs } = useValues(hogFunctionConfigurationLogic)

    const templating = props.input.templating ?? 'hog'

    if (!props.templating) {
        return (
            <LemonInput
                type="text"
                value={props.input.value}
                onChange={(val) => props.onChange?.({ ...props.input, value: val })}
            />
        )
    }

    return (
        <span className={clsx('group relative', props.className)}>
            <CodeEditorInline
                minHeight="37" // Match other inputs
                value={props.input.value ?? ''}
                onChange={(val) => props.onChange?.({ ...props.input, value: val ?? '' })}
                language={props.input.templating === 'hog' ? 'hogTemplate' : 'liquid'}
                globals={sampleGlobalsWithInputs}
            />
            <span className="absolute top-0 right-0 z-10 p-px opacity-0 transition-opacity group-hover:opacity-100">
                <HogFunctionTemplateSuggestionsButton
                    templating={templating}
                    value={props.input.value}
                    setTemplating={(templating) => props.onChange?.({ ...props.input, templating })}
                    onOptionSelect={(option) => {
                        props.onChange?.({ ...props.input, value: `${props.input.value} {${option.example}}` })
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
}: {
    input: HogFunctionInputType
    onChange?: (value: HogFunctionInputType) => void
    templating: boolean
}): JSX.Element {
    const value = input.value ?? {}
    const [entries, setEntries] = useState<[string, string][]>(Object.entries(value))
    const prevFilteredEntriesRef = useRef<[string, string][]>(entries)

    useEffect(() => {
        // NOTE: Filter out all empty entries as fetch will throw if passed in
        const filteredEntries = entries.filter(([key, val]) => key.trim() !== '' || val.trim() !== '')

        // Compare with previous filtered entries to avoid unnecessary updates
        if (objectsEqual(filteredEntries, prevFilteredEntriesRef.current)) {
            return
        }

        // Update the ref with current filtered entries
        prevFilteredEntriesRef.current = filteredEntries

        const val = Object.fromEntries(filteredEntries)
        onChange?.({ ...input, value: val })
    }, [entries, onChange])

    return (
        <div className="deprecated-space-y-2">
            {entries.map(([key, val], index) => (
                <div className="flex gap-2 items-center" key={index}>
                    <LemonInput
                        value={key}
                        className="flex-1 min-w-60"
                        onChange={(key) => {
                            const newEntries = [...entries]
                            newEntries[index] = [key, newEntries[index][1]]
                            setEntries(newEntries)
                        }}
                        placeholder="Key"
                    />

                    <HogFunctionTemplateInput
                        className="overflow-hidden flex-2"
                        input={{ ...input, value: val }}
                        onChange={(val) => {
                            const newEntries = [...entries]
                            newEntries[index] = [newEntries[index][0], val.value ?? '']
                            if (val.templating) {
                                onChange?.({ ...input, templating: val.templating })
                            }
                            setEntries(newEntries)
                        }}
                        templating={templating}
                    />

                    <LemonButton
                        icon={<IconX />}
                        size="small"
                        onClick={() => {
                            const newEntries = [...entries]
                            newEntries.splice(index, 1)
                            setEntries(newEntries)
                        }}
                    />
                </div>
            ))}
            <LemonButton
                icon={<IconPlus />}
                size="small"
                type="secondary"
                onClick={() => {
                    setEntries([...entries, ['', '']])
                }}
            >
                Add entry
            </LemonButton>
        </div>
    )
}

export function HogFunctionInputRenderer({ onChange, schema, disabled, input }: HogFunctionInputProps): JSX.Element {
    const templating = schema.templating ?? true

    const onValueChange = (value: any): void => onChange?.({ ...input, value })
    switch (schema.type) {
        case 'string':
            return (
                <HogFunctionTemplateInput
                    input={input}
                    onChange={disabled ? () => {} : onChange}
                    className="ph-no-capture"
                    templating={templating}
                />
            )
        case 'number':
            return <LemonInput type="number" value={input.value} onChange={onValueChange} className="ph-no-capture" />
        case 'json':
            return (
                <JsonConfigField input={input} onChange={onChange} className="ph-no-capture" templating={templating} />
            )
        case 'choice':
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
            return <DictionaryField input={input} onChange={onChange} templating={templating} />
        case 'boolean':
            return (
                <LemonSwitch checked={input.value} onChange={(checked) => onValueChange(checked)} disabled={disabled} />
            )
        case 'integration':
            return <HogFunctionInputIntegration schema={schema} value={input.value} onChange={onValueChange} />
        case 'integration_field':
            return <HogFunctionInputIntegrationField schema={schema} value={input.value} onChange={onValueChange} />
        case 'email':
            return <EmailTemplateField schema={schema} value={input.value} onChange={onValueChange} />
        default:
            return (
                <strong className="text-danger">
                    Unknown field type "<code>{schema.type}</code>".
                </strong>
            )
    }
}

type HogFunctionInputSchemaControlsProps = {
    value: HogFunctionInputSchemaType
    onChange: (value: HogFunctionInputSchemaType | null) => void
    onDone: () => void
    supportsSecrets: boolean
}

function HogFunctionInputSchemaControls({
    value,
    onChange,
    onDone,
    supportsSecrets,
}: HogFunctionInputSchemaControlsProps): JSX.Element {
    const _onChange = (data: Partial<HogFunctionInputSchemaType> | null): void => {
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
                    options={typeList.map((type) => ({
                        label: capitalizeFirstLetter(type),
                        value: type,
                    }))}
                    value={value.type}
                    className="w-30"
                    onChange={(type) => _onChange({ type })}
                />
                <LemonCheckbox
                    size="small"
                    checked={value.required}
                    onChange={(required) => _onChange({ required })}
                    label="Required"
                    bordered
                />
                {supportsSecrets ? (
                    <LemonCheckbox
                        size="small"
                        checked={value.secret}
                        onChange={(secret) => _onChange({ secret })}
                        label="Secret"
                        bordered
                    />
                ) : null}
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
                <HogFunctionInputRenderer
                    schema={value}
                    input={{ value: value.default }}
                    onChange={(val) => _onChange({ default: val.value })}
                />
            </LemonField.Pure>
        </div>
    )
}

export function HogFunctionInputWithSchema({
    schema,
    configuration,
    setConfigurationValue,
}: HogFunctionInputWithSchemaProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: schema.key })
    const { showSource } = useValues(hogFunctionConfigurationLogic)
    const [editing, setEditing] = useState(false)

    const value = configuration.inputs?.[schema.key] ?? { value: null }

    const onSchemaChange = (newSchema: HogFunctionInputSchemaType | null): void => {
        let inputsSchema = configuration.inputs_schema || []
        if (!newSchema) {
            inputsSchema = inputsSchema.filter((s) => s.key !== schema.key)
        } else {
            const modifiedSchema = { ...schema, ...newSchema }
            inputsSchema = inputsSchema.map((s) => (s.key === schema.key ? modifiedSchema : s))
        }

        if (newSchema?.key) {
            setConfigurationValue(`inputs.${newSchema.key}`, value)
        }

        if (newSchema?.type && newSchema.type !== schema.type) {
            setConfigurationValue(`inputs.${schema.key}`, null)
        }
        setConfigurationValue('inputs_schema', inputsSchema)
    }

    useEffect(() => {
        if (!showSource) {
            setEditing(false)
        }
    }, [showSource])

    const supportsSecrets = 'type' in configuration // no secrets for mapping inputs

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
                <LemonField name={`inputs.${schema.key}`} help={schema.description}>
                    {({
                        value,
                        onChange: _onChange,
                    }: {
                        value?: HogFunctionInputType
                        onChange: (val: HogFunctionInputType) => void
                    }) => {
                        const onChange = (newValue: HogFunctionInputType): void => {
                            _onChange({
                                // Keep the existing parts if they exist
                                ...value,
                                ...newValue,
                            })
                        }

                        return (
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
                                                onChange({ value: '' })
                                            }}
                                            size="small"
                                            type="secondary"
                                        >
                                            Edit
                                        </LemonButton>
                                    </div>
                                ) : (
                                    <HogFunctionInputRenderer
                                        schema={schema}
                                        input={value ?? { value: '' }}
                                        onChange={onChange}
                                    />
                                )}
                            </>
                        )
                    }}
                </LemonField>
            ) : (
                <div className="p-2 rounded border border-dashed deprecated-space-y-4">
                    <HogFunctionInputSchemaControls
                        value={schema}
                        onChange={onSchemaChange}
                        onDone={() => setEditing(false)}
                        supportsSecrets={supportsSecrets}
                    />
                </div>
            )}
        </div>
    )
}

export function HogFunctionInputs({
    configuration,
    setConfigurationValue,
}: HogFunctionInputsProps): JSX.Element | null {
    const { showSource } = useValues(hogFunctionConfigurationLogic)

    if (!configuration?.inputs_schema?.length) {
        if (!('type' in configuration)) {
            // If this is a mapping, don't show any error message.
            return null
        }
        return <span className="italic text-secondary">This function does not require any input variables.</span>
    }

    const inputSchemas = configuration.inputs_schema
    const inputSchemaIds = inputSchemas.map((schema) => schema.key)

    return (
        <>
            <DndContext
                collisionDetection={closestCenter}
                onDragEnd={({ active, over }) => {
                    if (over && active.id !== over.id) {
                        const oldIndex = inputSchemaIds.indexOf(active.id as string)
                        const newIndex = inputSchemaIds.indexOf(over.id as string)

                        setConfigurationValue('inputs_schema', arrayMove(inputSchemas, oldIndex, newIndex))
                    }
                }}
            >
                <SortableContext disabled={!showSource} items={inputSchemaIds} strategy={verticalListSortingStrategy}>
                    {configuration.inputs_schema
                        ?.filter((i) => !i.hidden)
                        .map((schema) => {
                            return (
                                <HogFunctionInputWithSchema
                                    key={schema.key}
                                    schema={schema}
                                    configuration={configuration}
                                    setConfigurationValue={setConfigurationValue}
                                />
                            )
                        })}
                </SortableContext>
            </DndContext>
        </>
    )
}
