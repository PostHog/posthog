import { Monaco } from '@monaco-editor/react'
import { IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeEditorResizeable } from 'lib/components/CodeEditors'
import { languages } from 'monaco-editor'
import { useEffect, useMemo, useState } from 'react'

import { groupsModel } from '~/models/groupsModel'
import { HogFunctionInputSchemaType } from '~/types'

export type HogFunctionInputProps = {
    schema: HogFunctionInputSchemaType
    value?: any
    onChange?: (value: any) => void
    disabled?: boolean
}

const SECRET_FIELD_VALUE = '********'

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
    className: string
    autoFocus: boolean
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

export function HogFunctionInput({ value, onChange, schema, disabled }: HogFunctionInputProps): JSX.Element {
    const [editingSecret, setEditingSecret] = useState(false)
    if (
        schema.secret &&
        !editingSecret &&
        value &&
        (value === SECRET_FIELD_VALUE || value.name === SECRET_FIELD_VALUE)
    ) {
        return (
            <LemonButton
                type="secondary"
                icon={<IconPencil />}
                onClick={() => {
                    onChange?.(schema.default || '')
                    setEditingSecret(true)
                }}
                disabled={disabled}
            >
                Reset secret variable
            </LemonButton>
        )
    }

    switch (schema.type) {
        case 'string':
            return (
                <LemonInput
                    value={value}
                    onChange={onChange}
                    autoFocus={editingSecret}
                    className="ph-no-capture"
                    disabled={disabled}
                />
            )
        case 'json':
            return (
                <JsonConfigField
                    value={value}
                    onChange={onChange}
                    autoFocus={editingSecret}
                    className="ph-no-capture"
                />
            )
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
        default:
            return (
                <strong className="text-danger">
                    Unknown field type "<code>{schema.type}</code>".
                    <br />
                    You may need to upgrade PostHog!
                </strong>
            )
    }
}
