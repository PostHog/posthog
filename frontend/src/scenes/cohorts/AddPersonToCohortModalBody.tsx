import { useActions, useValues } from 'kea'
import React from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'

import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'

export function AddPersonToCohortModalBody(): JSX.Element {
    const { query, cohortPersons, cohortUpdatesInProgress } = useValues(addPersonToCohortModalLogic)
    const { setQuery, addPersonToCohort } = useActions(addPersonToCohortModalLogic)

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
                        return <LemonTag type="success">Added</LemonTag>
                    }
                    return (
                        <LemonButton
                            type="secondary"
                            status="default"
                            size="small"
                            onClick={(e) => {
                                if (cohortUpdatesInProgress[id]) {
                                    return
                                }
                                e.preventDefault()
                                addPersonToCohort(id)
                            }}
                        >
                            {cohortUpdatesInProgress[id] ? <Spinner textColored /> : <IconPlusSmall />}
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
