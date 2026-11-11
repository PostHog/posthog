import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { biFilterValuesLogic } from './biFilterValuesLogic'
import { biMemberAliasesLogic } from './biMemberAliasesLogic'

export function BIMemberAliasesModal({ tabId }: { tabId: string }): JSX.Element {
    const logic = biMemberAliasesLogic({ tabId })
    const { field, draft, draftByValue, savedLabels, query } = useValues(logic)
    const { close, setAlias, save } = useActions(logic)
    const valuesLogic = biFilterValuesLogic({ query, active: !!field })
    const { options, optionsLoading, optionsError, hasMore, search } = useValues(valuesLogic)
    const { setSearch, loadMore, loadOptions } = useActions(valuesLogic)
    const members = [...new Set([null, ...(options ?? []), ...draft.map((alias) => alias.value)])].filter(
        (value) =>
            !search ||
            String(value ?? '(no value)')
                .toLowerCase()
                .includes(search.toLowerCase()) ||
            savedLabels.get(value)?.toLowerCase().includes(search.toLowerCase())
    )
    return (
        <LemonModal
            title={`Display aliases: ${field?.name ?? ''}`}
            isOpen={!!field}
            onClose={close}
            width={680}
            footer={
                <>
                    <LemonButton onClick={close}>Cancel</LemonButton>
                    <LemonButton type="primary" onClick={save}>
                        Save aliases
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <p>
                    Aliases change display labels only. Filtering, sorting, selections, SQL, and data exports use the
                    original values. Different values may share a label and stay separate.
                </p>
                <LemonInput
                    type="search"
                    value={search}
                    onChange={setSearch}
                    placeholder="Search values or saved aliases"
                    aria-label="Search member values and aliases"
                />
                {optionsError && (
                    <div role="alert">
                        Could not load values. Saved aliases can still be edited.{' '}
                        <LemonButton onClick={() => loadOptions()} loading={optionsLoading}>
                            Retry
                        </LemonButton>
                    </div>
                )}
                <LemonTable
                    key={search}
                    pagination={{ pageSize: 50 }}
                    size="small"
                    loading={optionsLoading}
                    dataSource={members.map((value) => ({ value }))}
                    rowKey={(row) => JSON.stringify(row.value)}
                    columns={[
                        {
                            title: 'Original value',
                            key: 'value',
                            render: (_, { value }) =>
                                value === null ? '(no value)' : value === '' ? '(empty string)' : value,
                        },
                        {
                            title: 'Display alias',
                            key: 'alias',
                            render: (_, { value }) => (
                                <LemonInput
                                    value={draftByValue.get(value) ?? ''}
                                    onChange={(label) => setAlias(value, label)}
                                    placeholder="Original value"
                                    aria-label={`Alias for ${value ?? '(no value)'}`}
                                    maxLength={200}
                                />
                            ),
                        },
                    ]}
                />
                {hasMore && (
                    <LemonButton onClick={loadMore} loading={optionsLoading}>
                        Load more values
                    </LemonButton>
                )}
                <p className="text-xs text-secondary">
                    Clear an alias to restore the original value. Changes apply only after Save aliases.
                </p>
            </div>
        </LemonModal>
    )
}
