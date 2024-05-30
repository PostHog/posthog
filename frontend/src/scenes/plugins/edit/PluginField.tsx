import { Monaco } from '@monaco-editor/react'
import { IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { PluginConfigSchema } from '@posthog/plugin-scaffold/src/types'
import { useValues } from 'kea'
import { CodeEditor } from 'lib/components/CodeEditors'
import { languages } from 'monaco-editor'
import { useEffect, useMemo, useState } from 'react'
import { SECRET_FIELD_VALUE } from 'scenes/pipeline/configUtils'

import { groupsModel } from '~/models/groupsModel'

function useAutocompleteOptions(): languages.CompletionItem[] {
    const { groupTypes } = useValues(groupsModel)

    return useMemo(() => {
        const options = [
            ['event', 'The entire event payload as a JSON object'],
            ['event.link', 'URL to the event in PostHog'],
            ['event.properties', 'Properties of the event'],
            ['event.properties.<key>', 'The individual property of the event'],
            ['person', 'The entire person payload as a JSON object'],
            ['person.link', 'URL to the person in PostHog'],
            ['person.properties', 'Properties of the person'],
            ['person.properties.<key>', 'The individual property of the person'],
        ]

        groupTypes.forEach((groupType) => {
            options.push([`groups.${groupType.group_type}`, `The entire group payload as a JSON object`])
            options.push([`groups.${groupType.group_type}.name`, `Display name of the group`])
            options.push([`groups.${groupType.group_type}.link`, `URL to the group in PostHog`])
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
    onChange?: (value: any) => void
    className: string
    autoFocus: boolean
    value: any
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
            triggerCharacters: ['{{'],
            provideCompletionItems: async (model, position) => {
                const word = model.getWordUntilPosition(position)

                const wordWithTrigger = model.getValueInRange({
                    startLineNumber: position.lineNumber,
                    startColumn: 0,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column,
                })

                if (wordWithTrigger.indexOf('{{') === -1) {
                    return { suggestions: [] }
                }

                const followingCharacters = model.getValueInRange({
                    startLineNumber: position.lineNumber,
                    startColumn: position.column,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column + 2,
                })

                const localSuggestions = suggestions.map((x) => ({
                    ...x,
                    insertText: x.insertText + (followingCharacters !== '}}' ? '}}' : ''),
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

    // TODO: Add auto complete suggestions to the editor

    return (
        <CodeEditor
            className="border rounded min-h-60"
            language="json"
            value={props.value}
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
        const validEntries = entries.filter(([key, val]) => key.trim() !== '' || val.trim() !== '')
        onChange?.(validEntries)
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
                            onChange?.(Object.fromEntries(newEntries))
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
                            onChange?.(Object.fromEntries(newEntries))
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
                            onChange?.(Object.fromEntries(newEntries))
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

export function PluginField({
    value,
    onChange,
    fieldConfig,
    disabled,
}: {
    value?: any
    onChange?: (value: any) => void
    fieldConfig: PluginConfigSchema
    disabled?: boolean
}): JSX.Element {
    const [editingSecret, setEditingSecret] = useState(false)
    if (
        fieldConfig.secret &&
        !editingSecret &&
        value &&
        (value === SECRET_FIELD_VALUE || value.name === SECRET_FIELD_VALUE)
    ) {
        return (
            <LemonButton
                type="secondary"
                icon={<IconPencil />}
                onClick={() => {
                    onChange?.(fieldConfig.default || '')
                    setEditingSecret(true)
                }}
                disabled={disabled}
            >
                Reset secret {fieldConfig.type === 'attachment' ? 'attachment' : 'field'}
            </LemonButton>
        )
    }

    return fieldConfig.type === 'attachment' ? (
        <>
            {value?.name ? <span>Selected file: {value.name}</span> : null}
            <LemonFileInput
                accept="*"
                multiple={false}
                onChange={(files) => onChange?.(files[0])}
                value={value?.size ? [value] : []}
                showUploadedFiles={false}
            />
        </>
    ) : fieldConfig.type === 'string' ? (
        <LemonInput
            value={value}
            onChange={onChange}
            autoFocus={editingSecret}
            className="ph-no-capture"
            disabled={disabled}
        />
    ) : fieldConfig.type === 'json' ? (
        <JsonConfigField value={value} onChange={onChange} autoFocus={editingSecret} className="ph-no-capture" />
    ) : fieldConfig.type === 'choice' ? (
        <LemonSelect
            fullWidth
            value={value}
            className="ph-no-capture"
            onChange={onChange}
            options={fieldConfig.choices.map((choice) => {
                return { label: choice, value: choice }
            })}
            disabled={disabled}
        />
    ) : fieldConfig.type === 'dictionary' ? (
        <DictionaryField value={value} onChange={onChange} />
    ) : (
        <strong className="text-danger">
            Unknown field type "<code>{fieldConfig.type}</code>".
            <br />
            You may need to upgrade PostHog!
        </strong>
    )
}
