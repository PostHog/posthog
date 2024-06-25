import { closestCenter, DndContext } from '@dnd-kit/core'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Monaco } from '@monaco-editor/react'
import { IconGear, IconPlus, IconTrash, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonSelect,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { capitalizeFirstLetter } from 'lib/utils'
import { languages } from 'monaco-editor'
import { useEffect, useMemo, useState } from 'react'

import { groupsModel } from '~/models/groupsModel'
import { HogFunctionInputSchemaType } from '~/types'

import { HogFunctionInputIntegration } from './integrations/HogFunctionInputIntegration'
import { HogFunctionInputIntegrationField } from './integrations/HogFunctionInputIntegrationField'
import { pipelineHogFunctionConfigurationLogic } from './pipelineHogFunctionConfigurationLogic'

export type HogFunctionInputProps = {
    schema: HogFunctionInputSchemaType
    value?: any
    onChange?: (value: any) => void
    disabled?: boolean
}

export type HogFunctionInputWithSchemaProps = {
    schema: HogFunctionInputSchemaType
}

const typeList = ['string', 'boolean', 'dictionary', 'choice', 'json', 'integration'] as const

function useAutocompleteOptions(): languages.CompletionItem[] {
    const { groupTypes } = useValues(groupsModel)

    return useMemo(() => {
        const options = [
            ['event', 'The entire event payload as a JSON object'],
            ['event.name', 'The name of the event e.g. $pageview'],
            ['event.distinct_id', 'The distinct_id of the event'],
            ['event.timestamp', 'The timestamp of the event'],
            ['event.url', 'URL to the event in PostHog'],
            ['event.properties', 'Properties of the event'],
            ['event.properties.<key>', 'The individual property of the event'],
            ['person', 'The entire person payload as a JSON object'],
            ['project.uuid', 'The UUID of the Person in PostHog'],
            ['person.url', 'URL to the person in PostHog'],
            ['person.properties', 'Properties of the person'],
            ['person.properties.<key>', 'The individual property of the person'],
            ['project.id', 'ID of the project in PostHog'],
            ['project.name', 'Name of the project'],
            ['project.url', 'URL to the project in PostHog'],
            ['source.name', 'Name of the source of this message'],
            ['source.url', 'URL to the source of this message in PostHog'],
        ]

        groupTypes.forEach((groupType) => {
            options.push([`groups.${groupType.group_type}`, `The entire group payload as a JSON object`])
            options.push([`groups.${groupType.group_type}.id`, `The ID or 'key' of the group`])
            options.push([`groups.${groupType.group_type}.url`, `URL to the group in PostHog`])
            options.push([`groups.${groupType.group_type}.properties`, `Properties of the group`])
            options.push([`groups.${groupType.group_type}.properties.<key>`, `The individual property of the group`])
            options.push([`groups.${groupType.group_type}.index`, `Index of the group`])
        })

        const items: languages.CompletionItem[] = options.map(([key, value]) => {
            return {
                label: key,
                kind: languages.CompletionItemKind.Variable,
                detail: value,
                insertText: key,
                range: {
                    startLineNumber: 1,
                    endLineNumber: 1,
                    startColumn: 0,
                    endColumn: 0,
                },
            }
        })

        return items
    }, [groupTypes])
}

function JsonConfigField(props: {
    onChange?: (value: string) => void
    className?: string
    autoFocus?: boolean
    value?: string
}): JSX.Element {
    const suggestions = useAutocompleteOptions()
    const [monaco, setMonaco] = useState<Monaco>()

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.setLanguageConfiguration('json', {
            wordPattern: /[a-zA-Z0-9_\-.]+/,
        })

        const provider = monaco.languages.registerCompletionItemProvider('json', {
            triggerCharacters: ['{', '{{'],
            provideCompletionItems: async (model, position) => {
                const word = model.getWordUntilPosition(position)

                const wordWithTrigger = model.getValueInRange({
                    startLineNumber: position.lineNumber,
                    startColumn: 0,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column,
                })

                if (wordWithTrigger.indexOf('{') === -1) {
                    return { suggestions: [] }
                }

                const localSuggestions = suggestions.map((x) => ({
                    ...x,
                    insertText: x.insertText,
                    range: {
                        startLineNumber: position.lineNumber,
                        endLineNumber: position.lineNumber,
                        startColumn: word.startColumn,
                        endColumn: word.endColumn,
                    },
                }))

                return {
                    suggestions: localSuggestions,
                    incomplete: false,
                }
            },
        })

        return () => provider.dispose()
    }, [suggestions, monaco])

    return (
        <CodeEditorResizeable
            language="json"
            value={typeof props.value !== 'string' ? JSON.stringify(props.value, null, 2) : props.value}
            onChange={(v) => props.onChange?.(v ?? '')}
            options={{
                lineNumbers: 'off',
                minimap: {
                    enabled: false,
                },
                quickSuggestions: {
                    other: true,
                    strings: true,
                },
                suggest: {
                    showWords: false,
                    showFields: false,
                    showKeywords: false,
                },
                scrollbar: {
                    vertical: 'hidden',
                    verticalScrollbarSize: 0,
                },
            }}
            onMount={(_editor, monaco) => {
                setMonaco(monaco)
            }}
        />
    )
}

function DictionaryField({ onChange, value }: { onChange?: (value: any) => void; value: any }): JSX.Element {
    const [entries, setEntries] = useState<[string, string][]>(Object.entries(value ?? {}))

    useEffect(() => {
        // NOTE: Filter out all empty entries as fetch will throw if passed in
        const val = Object.fromEntries(entries.filter(([key, val]) => key.trim() !== '' || val.trim() !== ''))
        onChange?.(val)
    }, [entries])

    return (
        <div className="space-y-2">
            {entries.map(([key, val], index) => (
                <div className="flex items-center gap-2" key={index}>
                    <LemonInput
                        value={key}
                        className="flex-1"
                        onChange={(key) => {
                            const newEntries = [...entries]
                            newEntries[index] = [key, newEntries[index][1]]
                            setEntries(newEntries)
                        }}
                        placeholder="Key"
                    />

                    <LemonInput
                        className="flex-1"
                        value={val}
                        onChange={(val) => {
                            const newEntries = [...entries]
                            newEntries[index] = [newEntries[index][0], val]
                            setEntries(newEntries)
                        }}
                        placeholder="Value"
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

export function HogFunctionInputRenderer({ value, onChange, schema, disabled }: HogFunctionInputProps): JSX.Element {
    switch (schema.type) {
        case 'string':
            return <LemonInput value={value} onChange={onChange} className="ph-no-capture" disabled={disabled} />
        case 'json':
            return <JsonConfigField value={value} onChange={onChange} className="ph-no-capture" />
        case 'choice':
            return (
                <LemonSelect
                    fullWidth
                    value={value}
                    className="ph-no-capture"
                    onChange={onChange}
                    options={schema.choices ?? []}
                    disabled={disabled}
                />
            )
        case 'dictionary':
            return <DictionaryField value={value} onChange={onChange} />

        case 'boolean':
            return <LemonCheckbox checked={value} onChange={(checked) => onChange?.(checked)} disabled={disabled} />
        case 'integration':
            return <HogFunctionInputIntegration schema={schema} value={value} onChange={onChange} />
        case 'integration_field':
            return <HogFunctionInputIntegrationField schema={schema} value={value} onChange={onChange} />
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
}

function HogFunctionInputSchemaControls({ value, onChange, onDone }: HogFunctionInputSchemaControlsProps): JSX.Element {
    const _onChange = (data: Partial<HogFunctionInputSchemaType> | null): void => {
        onChange(data ? { ...value, ...data } : null)
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex-1 flex items-center gap-2 flex-wrap">
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
                <LemonCheckbox
                    size="small"
                    checked={value.secret}
                    onChange={(secret) => _onChange({ secret })}
                    label="Secret"
                    bordered
                />
                <div className="flex-1" />
                <LemonButton status="danger" icon={<IconTrash />} size="small" onClick={() => onChange(null)} />
                <LemonButton size="small" onClick={() => onDone()}>
                    Done
                </LemonButton>
            </div>
            <div className="flex-1 flex gap-2 flex-wrap">
                <LemonField.Pure label="Display label">
                    <LemonInput
                        className="min-w-60"
                        size="small"
                        value={value.label}
                        onChange={(label) => _onChange({ label })}
                        placeholder="Display label"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Input variable name">
                    <LemonInput
                        size="small"
                        value={value.key}
                        onChange={(key) => _onChange({ key })}
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
                        options={[{ label: 'Slack', value: 'slack' }]}
                        placeholder="Choose kind"
                    />
                </LemonField.Pure>
            )}

            <LemonField.Pure label="Default value">
                <HogFunctionInputRenderer
                    schema={value}
                    value={value.default}
                    onChange={(val) => _onChange({ default: val })}
                />
            </LemonField.Pure>
        </div>
    )
}

export function HogFunctionInputWithSchema({ schema }: HogFunctionInputWithSchemaProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: schema.key })
    const { showSource, configuration } = useValues(pipelineHogFunctionConfigurationLogic)
    const { setConfigurationValue } = useActions(pipelineHogFunctionConfigurationLogic)
    const [editing, setEditing] = useState(showSource)

    const value = configuration.inputs?.[schema.key]

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
                    {({ value, onChange }) => {
                        return (
                            <>
                                <div className="flex items-center gap-2">
                                    <LemonLabel
                                        className={showSource ? 'cursor-grab' : ''}
                                        showOptional={!schema.required}
                                        {...attributes}
                                        {...listeners}
                                    >
                                        {schema.label || schema.key}
                                    </LemonLabel>
                                    {showSource ? (
                                        <>
                                            <LemonTag type="muted" className="font-mono">
                                                inputs.{schema.key}
                                            </LemonTag>
                                            <div className="flex-1" />
                                            <LemonButton
                                                size="small"
                                                noPadding
                                                icon={<IconGear />}
                                                onClick={() => setEditing(true)}
                                            />
                                        </>
                                    ) : null}
                                </div>
                                <HogFunctionInputRenderer
                                    schema={schema}
                                    value={value?.value}
                                    onChange={(val) => onChange({ value: val })}
                                />
                            </>
                        )
                    }}
                </LemonField>
            ) : (
                <div className="border rounded p-2 border-dashed space-y-4">
                    <HogFunctionInputSchemaControls
                        value={schema}
                        onChange={onSchemaChange}
                        onDone={() => setEditing(false)}
                    />
                </div>
            )}
        </div>
    )
}

export function HogFunctionInputs(): JSX.Element {
    const { showSource, configuration } = useValues(pipelineHogFunctionConfigurationLogic)
    const { setConfigurationValue } = useActions(pipelineHogFunctionConfigurationLogic)

    if (!configuration?.inputs_schema?.length) {
        return <span className="italic text-muted-alt">This function does not require any input variables.</span>
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
                    {configuration.inputs_schema?.map((schema) => {
                        return <HogFunctionInputWithSchema key={schema.key} schema={schema} />
                    })}
                </SortableContext>
            </DndContext>
        </>
    )
}
