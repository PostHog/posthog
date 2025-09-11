import { useActions, useValues } from 'kea'
import React from 'react'

import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

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
                    if (isInCohort) {
                        return <LemonTag type="success">In Cohort</LemonTag>
                    }
                    const isAdded = personsToAddToCohort[id] != null
                    return (
                        <LemonButton
                            type="secondary"
                            status={isAdded ? 'danger' : 'default'}
                            size="small"
                            onClick={(e) => {
                                e.preventDefault()
                                if (isAdded) {
                                    removePerson(id)
                                } else {
                                    addPerson(id)
                                }
                            }}
                        >
                            {isAdded ? <IconMinusSmall /> : <IconPlusSmall />}
                        </LemonButton>
                    )
                },
            },
        },
        showOpenEditorButton: false,
    }
    return (
        <div className="min-w-180">
            <Query query={query} setQuery={setQuery} context={context} />
        </div>
    )
}
