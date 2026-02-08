import './AddPersonToCohortModalBody.scss'

import { useActions, useValues } from 'kea'
import React from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTag } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'

import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'

export function AddPersonToCohortModalBody(): JSX.Element {
    const { query, cohortPersons, personsToAddToCohort } = useValues(addPersonToCohortModalLogic)
    const { setQuery, addPerson, removePerson } = useActions(addPersonToCohortModalLogic)

    const cohortPersonsSet = React.useMemo(() => {
        return new Set(cohortPersons.results.map((p) => p.id))
    }, [cohortPersons])

    const context: QueryContext = {
        columns: {
            id: {
                renderTitle: () => null,
                render: (props) => {
                    const id = props.value as string
                    const isInCohort = cohortPersonsSet.has(id)
                    const isAdded = personsToAddToCohort[id] != null

                    if (isInCohort) {
                        return (
                            <LemonCheckbox
                                checked={true}
                                disabled
                                data-attr="cohort-person-checkbox"
                            />
                        )
                    }

                    return (
                        <LemonCheckbox
                            checked={isAdded}
                            onChange={() => {
                                if (isAdded) {
                                    removePerson(id)
                                } else {
                                    addPerson(id)
                                }
                            }}
                            data-attr="cohort-person-checkbox"
                        />
                    )
                },
            },
            person_display_name: {
                render: (props) => {
                    const value = props.value as { id: string; display_name: string } | null
                    const record = props.record as any[]
                    const id = record?.[0] as string | undefined
                    const isInCohort = id ? cohortPersonsSet.has(id) : false
                    const personUrl = value?.id ? urls.personByUUID(value.id) : undefined

                    return (
                        <div className="flex items-center justify-between w-full gap-2">
                            <div className="flex items-center gap-2 min-w-0">
                                {value ? (
                                    <PersonDisplay
                                        person={{ id: value.id }}
                                        displayName={value.display_name}
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
                    )
                },
            },
        },
        showOpenEditorButton: false,
    }
    return (
        <div className="min-w-180 AddPersonToCohortModalBody">
            <Query query={query} setQuery={setQuery} context={context} />
        </div>
    )
}
