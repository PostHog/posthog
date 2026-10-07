import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { BIField } from '~/queries/schema/schema-business-intelligence'

import { BIDataPaneField } from './BIDataPaneField'
import { isNumericBIField } from './biEditorTypes'
import { biPropertyFieldsLogic } from './biPropertyFieldsLogic'

export function BIPropertyFieldGroup({
    field,
    tabId,
    path,
    dataPaneSearch,
}: {
    field: BIField
    tabId: string
    path: string[]
    dataPaneSearch: string
}): JSX.Element {
    const logic = biPropertyFieldsLogic({ field, tabId, dataPaneSearch })
    const { expanded, page, pageLoading, fields, error, search } = useValues(logic)
    const { toggleExpanded, loadPage, setSearch } = useActions(logic)
    return (
        <div className="min-w-0" data-attr="bi-editor-property-group">
            <div className="flex min-w-0 items-center">
                {dataPaneSearch.trim() ? (
                    <IconChevronRight className="m-1 shrink-0 rotate-90" />
                ) : (
                    <LemonButton
                        size="xxsmall"
                        type="tertiary"
                        icon={<IconChevronRight className={cn(expanded && 'rotate-90')} />}
                        aria-label={`Browse ${field.name}`}
                        aria-expanded={expanded}
                        loading={pageLoading}
                        onClick={toggleExpanded}
                    />
                )}
                <BIDataPaneField field={{ ...field, type: 'json' }} measure={false} path={path} />
            </div>
            {expanded ? (
                <div className="ml-2 min-w-0 border-l pl-1">
                    {!dataPaneSearch.trim() ? (
                        <LemonInput
                            size="small"
                            type="search"
                            value={search}
                            onChange={setSearch}
                            placeholder="Search properties"
                            aria-label={`Search ${field.name}`}
                        />
                    ) : null}
                    {fields.map((property) => (
                        <BIDataPaneField
                            key={property.id}
                            field={property}
                            measure={isNumericBIField(property)}
                            path={field.name.split('.')}
                        />
                    ))}
                    {pageLoading ? (
                        <div className="flex items-center gap-1 p-2 text-xs text-secondary">
                            <Spinner /> Loading properties
                        </div>
                    ) : null}
                    {error ? (
                        <div className="p-2 text-xs">
                            <span>Couldn't load properties.</span>
                            <LemonButton
                                size="xsmall"
                                loading={pageLoading}
                                onClick={() => loadPage({ offset: page?.results.length ?? 0 })}
                            >
                                Retry
                            </LemonButton>
                        </div>
                    ) : null}
                    {!pageLoading && !error && page && !fields.length ? (
                        <span className="block p-2 text-xs text-secondary">
                            {search ? 'No matching properties' : 'No properties found'}
                        </span>
                    ) : null}
                    {page && !error && page.results.length < page.count ? (
                        <LemonButton
                            size="xsmall"
                            loading={pageLoading}
                            onClick={() => loadPage({ offset: page.results.length })}
                        >
                            Load more
                        </LemonButton>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}
