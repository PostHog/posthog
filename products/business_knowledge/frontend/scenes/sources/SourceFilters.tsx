import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LIBRARY_SCOPE_ALL, LIBRARY_SCOPE_UNFILED, businessKnowledgeLogic } from './businessKnowledgeLogic'

export function SourceFilters(): JSX.Element {
    const { searchTerm, sourceTypeFilter, addedByFilter, libraries, libraryScope } = useValues(businessKnowledgeLogic)
    const { setSearchTerm, setSourceTypeFilter, setAddedByFilter, setLibraryScope } = useActions(businessKnowledgeLogic)

    return (
        <div className="flex flex-wrap gap-2 items-center">
            <LemonInput
                type="search"
                placeholder="Search by name or URL"
                value={searchTerm}
                onChange={setSearchTerm}
                className="max-w-80"
            />
            <LemonSelect
                value={sourceTypeFilter}
                onChange={setSourceTypeFilter}
                options={[
                    { value: 'all', label: 'All types' },
                    { value: 'text', label: 'Text' },
                    { value: 'url', label: 'URL' },
                    { value: 'file', label: 'File' },
                ]}
            />
            <LemonSelect
                value={addedByFilter}
                onChange={setAddedByFilter}
                options={[
                    { value: 'all', label: 'All sources' },
                    { value: 'human', label: 'Human' },
                    { value: 'learned', label: 'Learned' },
                ]}
                data-attr="business-knowledge-added-by-filter"
            />
            {libraries.length > 0 && (
                <LemonSelect
                    value={libraryScope}
                    onChange={setLibraryScope}
                    options={[
                        { value: LIBRARY_SCOPE_ALL, label: 'All libraries' },
                        ...libraries.map((library) => ({ value: library.id, label: library.name })),
                        { value: LIBRARY_SCOPE_UNFILED, label: 'No library' },
                    ]}
                    data-attr="business-knowledge-library-filter"
                />
            )}
        </div>
    )
}
