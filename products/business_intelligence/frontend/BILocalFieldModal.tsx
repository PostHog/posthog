import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { biEditorLogic } from './biEditorLogic'
import { buildBIFilterOptionsQuery } from './biEditorTypes'
import { biFilterValuesLogic } from './biFilterValuesLogic'
import { localFieldError } from './biLocalFields'

export function BILocalFieldModal(): JSX.Element | null {
    const { localFieldDraft: draft, config } = useValues(biEditorLogic)
    const { setLocalFieldDraft, saveLocalField } = useActions(biEditorLogic)
    const definition = draft?.localDefinition
    const sourceField =
        draft && definition ? { ...draft, localDefinition: undefined, expression: definition.expression } : null
    const valuesLogic = biFilterValuesLogic({
        query: sourceField
            ? buildBIFilterOptionsQuery(
                  { ...config, filters: [...config.filters, { field: sourceField, operator: 'in', value: '' }] },
                  config.filters.length
              )
            : null,
        active: definition?.kind === 'groups',
        config,
    })
    const { options, optionsLoading, hasMore, optionsError } = useValues(valuesLogic)
    const { setSearch, loadMore, loadOptions } = useActions(valuesLogic)
    if (!draft || !definition) {
        return null
    }
    const error = !draft.name.trim() ? 'Enter a name' : localFieldError(definition)
    return (
        <LemonModal
            isOpen
            data-attr="bi-local-field-modal"
            onClose={() => setLocalFieldDraft(null)}
            title={definition.kind === 'bins' ? 'Numeric bins' : 'Category groups'}
            footer={
                <LemonButton type="primary" onClick={saveLocalField} disabledReason={error}>
                    Save local field
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-3">
                <p className="m-0 text-secondary">
                    This definition stays in this worksheet. Drag the new field from Dimensions onto a shelf to use it.
                </p>
                <LemonField.Pure label="Name">
                    <LemonInput
                        aria-label="Local field name"
                        value={draft.name}
                        onChange={(name) => setLocalFieldDraft({ ...draft, name })}
                    />
                </LemonField.Pure>
                <p className="m-0 text-xs text-secondary break-words">
                    Source: <code>{definition.expression}</code>
                </p>
                {definition.kind === 'bins' ? (
                    <>
                        <LemonField.Pure label="Bin width">
                            <LemonInput
                                type="number"
                                aria-label="Bin width"
                                value={definition.width}
                                onChange={(width) =>
                                    setLocalFieldDraft({
                                        ...draft,
                                        localDefinition: { ...definition, width: width ?? 0 },
                                    })
                                }
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Starting point">
                            <LemonInput
                                type="number"
                                aria-label="Starting point"
                                value={definition.origin}
                                onChange={(origin) =>
                                    setLocalFieldDraft({
                                        ...draft,
                                        localDefinition: { ...definition, origin: origin ?? 0 },
                                    })
                                }
                            />
                        </LemonField.Pure>
                        <p className="m-0 text-xs">
                            Each bin is labeled by its lower bound, includes that bound, and excludes the next one.
                            Missing values stay missing.
                        </p>
                    </>
                ) : (
                    <>
                        {definition.groups.map((group, index) => (
                            <div key={index} className="flex flex-col gap-2 rounded border p-2">
                                <LemonInput
                                    aria-label={`Group ${index + 1} name`}
                                    placeholder="Group name"
                                    value={group.name}
                                    onChange={(name) =>
                                        setLocalFieldDraft({
                                            ...draft,
                                            localDefinition: {
                                                ...definition,
                                                groups: definition.groups.map((current, i) =>
                                                    i === index ? { ...current, name } : current
                                                ),
                                            },
                                        })
                                    }
                                />
                                <LemonInputSelect
                                    mode="multiple"
                                    value={group.values}
                                    options={(options ?? []).map((value) => ({
                                        key: value,
                                        label: value || '(empty string)',
                                    }))}
                                    loading={optionsLoading}
                                    onInputChange={setSearch}
                                    disableFiltering
                                    allowCustomValues
                                    disableCommaSplitting
                                    onChange={(values) =>
                                        setLocalFieldDraft({
                                            ...draft,
                                            localDefinition: {
                                                ...definition,
                                                groups: definition.groups.map((current, i) =>
                                                    i === index ? { ...current, values } : current
                                                ),
                                            },
                                        })
                                    }
                                    placeholder="Search or enter values"
                                />
                                <LemonButton
                                    size="xsmall"
                                    status="danger"
                                    onClick={() =>
                                        setLocalFieldDraft({
                                            ...draft,
                                            localDefinition: {
                                                ...definition,
                                                groups: definition.groups.filter((_, i) => i !== index),
                                            },
                                        })
                                    }
                                >
                                    Remove group
                                </LemonButton>
                            </div>
                        ))}
                        {optionsError && (
                            <LemonButton size="xsmall" onClick={() => loadOptions()} loading={optionsLoading}>
                                Retry loading values
                            </LemonButton>
                        )}
                        {hasMore && (
                            <LemonButton size="xsmall" loading={optionsLoading} onClick={loadMore}>
                                Load more values
                            </LemonButton>
                        )}
                        <LemonButton
                            size="small"
                            onClick={() =>
                                setLocalFieldDraft({
                                    ...draft,
                                    localDefinition: {
                                        ...definition,
                                        groups: [...definition.groups, { name: '', values: [] }],
                                    },
                                })
                            }
                        >
                            Add group
                        </LemonButton>
                        <LemonField.Pure label="Other values">
                            <LemonInput
                                value={definition.other}
                                onChange={(other) =>
                                    setLocalFieldDraft({ ...draft, localDefinition: { ...definition, other } })
                                }
                            />
                        </LemonField.Pure>
                        <p className="m-0 text-xs text-secondary">
                            Unlisted values use this label. Missing values stay missing.
                        </p>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
