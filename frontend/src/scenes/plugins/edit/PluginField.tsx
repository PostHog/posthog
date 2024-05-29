import { IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { PluginConfigSchema } from '@posthog/plugin-scaffold/src/types'
import { useValues } from 'kea'
import { CodeEditor } from 'lib/components/CodeEditors'
import { flattenObject } from 'lib/utils'
import { IDisposable, languages } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { SECRET_FIELD_VALUE } from 'scenes/pipeline/configUtils'

import { groupsModel } from '~/models/groupsModel'

function useAutocompleteOptions(): languages.CompletionItem[] {
    const { groupTypes } = useValues(groupsModel)

    const exampleEvent = {
        event: {
            link: 'https://example.com',
            name: 'event_name',
            properties: {
                key: 'value',
            },
        },
        person: {
            link: 'https://example.com',

            properties: {
                key: 'Choose your property',
            },
        },
        groups: {},
    }

    groupTypes.forEach((groupType) => {
        exampleEvent.groups[groupType.group_type] = {
            link: 'URL to the group in PostHog',
            name: 'Display name of the group',
            index: 'Index of the group',
            properties: {
                key: 'value',
            },
        }
    })

    const flattened = flattenObject(exampleEvent)

    const items: languages.CompletionItem[] = Object.entries(flattened).map(([key, value]) => {
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
}

function JsonConfigField(props: {
    onChange?: (value: any) => void
    className: string
    autoFocus: boolean
    value: any
}): JSX.Element {
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    const suggestions = useAutocompleteOptions()

    // TODO: Add auto complete suggestions to the editor

    return (
        <AutoSizer disableWidth className="min-h-60">
            {({ height }) => (
                <CodeEditor
                    className="border rounded overflow-hidden"
                    language="json"
                    value={props.value}
                    onChange={(v) => props.onChange?.(v ?? '')}
                    height={height}
                    options={{
                        lineNumbers: 'off',
                        minimap: {
                            enabled: false,
                        },
                        quickSuggestions: {
                            other: true,
                            strings: true,
                        },
                    }}
                    onMount={(_editor, monaco) => {
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

                                // const completionItems = response.suggestions

                                // const suggestions = completionItems.map<languages.CompletionItem>((item) => {
                                //     const kind = convertCompletionItemKind(item.kind)
                                //     const sortText = kindToSortText(item.kind, item.label)

                                //     return {
                                //         label: {
                                //             label: item.label,
                                //             detail: item.detail,
                                //         },
                                //         documentation: item.documentation,
                                //         insertText: item.insertText,
                                //         range: {
                                //             startLineNumber: position.lineNumber,
                                //             endLineNumber: position.lineNumber,
                                //             startColumn: word.startColumn,
                                //             endColumn: word.endColumn,
                                //         },
                                //         kind,
                                //         sortText,
                                //         command:
                                //             kind === languages.CompletionItemKind.Function
                                //                 ? {
                                //                       id: 'cursorLeft',
                                //                       title: 'Move cursor left',
                                //                   }
                                //                 : undefined,
                                //     }
                                // })

                                return {
                                    suggestions: localSuggestions,
                                    incomplete: false,
                                }
                            },
                        })

                        monacoDisposables.current.push(provider)
                    }}
                />
            )}
        </AutoSizer>
    )
}

function DictionaryField({ onChange, value }: { onChange?: (value: any) => void; value: any }): JSX.Element {
    const [entries, setEntries] = useState<[string, string][]>(Object.entries(value ?? {}))

    useEffect(() => {
        onChange?.(Object.fromEntries(entries))
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
