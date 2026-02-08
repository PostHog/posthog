import './AddPersonToCohortModalBody.scss'

import { BindLogic, useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useMemo, useState } from 'react'
import { List } from 'react-window'
import { useDebouncedCallback } from 'use-debounce'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTag } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'

const ROW_HEIGHT = 44
const DATA_NODE_KEY = 'addPersonToCohortModal'

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
    cohortPersonsSet: Set<string>
    personsToAddToCohort: Record<string, boolean>
    addPerson: (id: string) => void
    removePerson: (id: string) => void
}

const PersonRowComponent = ({
    index,
    style,
    persons,
    cohortPersonsSet,
    personsToAddToCohort,
    addPerson,
    removePerson,
}: PersonRowProps & { index: number; style: CSSProperties; ariaAttributes: Record<string, unknown> }): JSX.Element => {
    const person = persons[index]
    const isInCohort = cohortPersonsSet.has(person.id)
    const isAdded = personsToAddToCohort[person.id] != null
    const personUrl = person.displayName?.id ? urls.personByUUID(person.displayName.id) : undefined

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={style} className="AddPersonToCohortModalBody__row" data-attr="cohort-person-row">
            <LemonCheckbox
                checked={isInCohort || isAdded}
                disabled={isInCohort}
                onChange={() => {
                    if (isAdded) {
                        removePerson(person.id)
                    } else {
                        addPerson(person.id)
                    }
                }}
                data-attr="cohort-person-checkbox"
            />
            <div className="flex items-center justify-between flex-1 gap-2 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    {person.displayName ? (
                        <PersonDisplay
                            person={{ id: person.displayName.id }}
                            displayName={person.displayName.display_name}
                            withIcon
                            noLink
                            noPopover
                        />
                    ) : (
                        <span className="text-muted">Unknown person</span>
                    )}
                    {isInCohort && <LemonTag type="success">In cohort</LemonTag>}
                </div>
                {personUrl && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconExternal />}
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

export function AddPersonToCohortModalBody(): JSX.Element {
    const { query, cohortPersons, personsToAddToCohort } = useValues(addPersonToCohortModalLogic)
    const { setQuery, addPerson, removePerson } = useActions(addPersonToCohortModalLogic)

    const dataNodeLogicProps = useMemo(
        () => ({
            key: DATA_NODE_KEY,
            query,
        }),
        [query]
    )

    const { response, responseLoading, canLoadNextData, nextDataLoading } = useValues(dataNodeLogic(dataNodeLogicProps))
    const { loadNextData } = useActions(dataNodeLogic(dataNodeLogicProps))

    const cohortPersonsSet = useMemo(() => {
        return new Set(cohortPersons.results.map((p) => p.id))
    }, [cohortPersons])

    const persons = useMemo(() => parseResults(response?.results as any[][] | undefined), [response])

    const [searchValue, setSearchValue] = useState('')
    const debouncedSetSearch = useDebouncedCallback((value: string) => {
        setQuery({ ...query, search: value || undefined })
    }, 300)
    const handleSearchChange = useCallback(
        (value: string) => {
            setSearchValue(value)
            debouncedSetSearch(value)
        },
        [debouncedSetSearch]
    )

    const rowProps: PersonRowProps = useMemo(
        () => ({
            persons,
            cohortPersonsSet,
            personsToAddToCohort,
            addPerson,
            removePerson,
        }),
        [persons, cohortPersonsSet, personsToAddToCohort, addPerson, removePerson]
    )

    return (
        <div className="AddPersonToCohortModalBody">
            <LemonInput
                type="search"
                value={searchValue}
                placeholder="Search by name, email, Person ID or Distinct ID"
                data-attr="persons-search"
                onChange={handleSearchChange}
                fullWidth
                autoFocus
            />
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="AddPersonToCohortModalBody__list">
                    {responseLoading && persons.length === 0 ? (
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
                                        height={height}
                                        width="100%"
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
