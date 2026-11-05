import './AddPersonToCohortModalBody.scss'

import { BindLogic, useActions, useValues } from 'kea'
import { CSSProperties, useMemo, useState } from 'react'
import { List } from 'react-window'
import { useDebouncedCallback } from 'use-debounce'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTag } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ActorsQuery } from '~/queries/schema/schema-general'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

const ROW_HEIGHT = 44

interface PersonRowData {
    id: string
    displayName: { id: string; display_name: string } | null
}

function parseResults(results: any[][] | undefined): PersonRowData[] {
    if (!results) {
        return []
    }
    return results.map((row) => ({
        id: row[0] as string,
        displayName: row[1] as { id: string; display_name: string } | null,
    }))
}

interface PersonRowProps {
    persons: PersonRowData[]
    existingPersonsSet: Set<string> | undefined
    selectedPersons: Record<string, unknown>
    onAddPerson: (id: string, displayName: string | null) => void
    onRemovePerson: (id: string) => void
}

const PersonRowComponent = ({
    index,
    style,
    persons,
    existingPersonsSet,
    selectedPersons,
    onAddPerson,
    onRemovePerson,
}: PersonRowProps & { index: number; style: CSSProperties; ariaAttributes: Record<string, unknown> }): JSX.Element => {
    const person = persons[index]
    const isInCohort = existingPersonsSet?.has(person.id) ?? false
    const isSelected = person.id in selectedPersons
    const personUrl = person.displayName?.id ? urls.personByUUID(person.displayName.id) : undefined

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={style} className="AddPersonToCohortModalBody__row" data-attr="cohort-person-row">
            <LemonCheckbox
                checked={isInCohort || isSelected}
                disabledReason={isInCohort ? 'This person is already in the cohort' : null}
                onChange={() => {
                    if (isSelected) {
                        onRemovePerson(person.id)
                    } else {
                        onAddPerson(person.id, person.displayName?.display_name ?? null)
                    }
                }}
                fullWidth
                label={
                    person.displayName ? (
                        <PersonDisplay
                            person={{ id: person.displayName.id }}
                            displayName={person.displayName.display_name}
                            withIcon
                            noLink
                            noPopover
                        />
                    ) : (
                        <span className="text-muted">Unknown person</span>
                    )
                }
                data-attr="cohort-person-checkbox"
            />
            <div className="flex items-center gap-2 shrink-0">
                {isInCohort && <LemonTag type="success">In cohort</LemonTag>}
                {personUrl && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconExternal />}
                        hideExternalLinkIcon={true}
                        targetBlank
                        to={personUrl}
                        tooltip="Open person in new tab"
                        data-attr="cohort-person-open-in-new-tab"
                    />
                )}
            </div>
        </div>
    )
}

export interface PersonSelectListProps {
    query: ActorsQuery
    setQuery: (query: ActorsQuery) => void
    selectedPersons: Record<string, unknown>
    onAddPerson: (id: string, displayName: string | null) => void
    onRemovePerson: (id: string) => void
    existingPersonsSet?: Set<string>
    dataNodeKey: string
    autoFocus?: boolean
}

export function PersonSelectList({
    query,
    setQuery,
    selectedPersons,
    onAddPerson,
    onRemovePerson,
    existingPersonsSet,
    dataNodeKey,
    autoFocus,
}: PersonSelectListProps): JSX.Element {
    const dataNodeLogicProps = useMemo(
        () => ({
            key: dataNodeKey,
            query,
        }),
        [dataNodeKey, query]
    )

    const logic = dataNodeLogic(dataNodeLogicProps)
    const {
        response,
        responseLoading,
        responseError,
        responseErrorObject,
        queryCancelled,
        queryId,
        canLoadNextData,
        nextDataLoading,
    } = useValues(logic)
    const { loadNextData, loadData } = useActions(logic)

    const persons = useMemo(() => parseResults((response as Record<string, any> | null)?.results), [response])

    const [searchValue, setSearchValue] = useState('')
    const debouncedSetSearch = useDebouncedCallback((value: string) => {
        setQuery({ ...query, search: value || undefined })
    }, 300)

    const rowProps: PersonRowProps = useMemo(
        () => ({
            persons,
            existingPersonsSet,
            selectedPersons,
            onAddPerson,
            onRemovePerson,
        }),
        [persons, existingPersonsSet, selectedPersons, onAddPerson, onRemovePerson]
    )

    return (
        <div className="AddPersonToCohortModalBody">
            <LemonInput
                type="search"
                value={searchValue}
                placeholder="Search by name, email, Person ID or Distinct ID"
                data-attr="persons-search"
                onChange={(value: string) => {
                    setSearchValue(value)
                    debouncedSetSearch(value)
                }}
                fullWidth
                autoFocus={autoFocus}
            />
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="AddPersonToCohortModalBody__list">
                    {responseError ? (
                        <div className="flex h-full">
                            <InsightErrorState
                                query={query}
                                queryId={responseErrorObject?.queryId ?? queryId}
                                titleStatus={responseErrorObject?.status}
                                excludeDetail={queryCancelled}
                                onRetry={() => loadData('force_blocking')}
                                title={
                                    queryCancelled
                                        ? 'The search was cancelled'
                                        : response && 'error' in response
                                          ? response.error
                                          : responseError
                                }
                            />
                        </div>
                    ) : responseLoading && persons.length === 0 ? (
                        <div className="flex items-center justify-center h-full">
                            <Spinner className="text-2xl" />
                        </div>
                    ) : persons.length === 0 ? (
                        <div className="flex items-center justify-center h-full text-muted">
                            {searchValue ? 'No persons found matching your search.' : 'Search for persons to add.'}
                        </div>
                    ) : (
                        <AutoSizer
                            disableWidth
                            renderProp={({ height }) =>
                                height ? (
                                    <List<PersonRowProps>
                                        style={{ height, width: '100%' }}
                                        rowCount={persons.length}
                                        rowHeight={ROW_HEIGHT}
                                        overscanCount={10}
                                        rowProps={rowProps}
                                        rowComponent={PersonRowComponent}
                                    />
                                ) : null
                            }
                        />
                    )}
                    {canLoadNextData && persons.length > 0 && (
                        <div className="p-2">
                            <LemonButton
                                onClick={loadNextData}
                                loading={nextDataLoading}
                                type="secondary"
                                size="small"
                                fullWidth
                                center
                                data-attr="cohort-person-load-more"
                            >
                                Load more
                            </LemonButton>
                        </div>
                    )}
                </div>
            </BindLogic>
        </div>
    )
}
