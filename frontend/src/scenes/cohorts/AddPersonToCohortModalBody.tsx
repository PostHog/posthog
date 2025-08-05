import { useActions, useValues } from 'kea'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { LemonButton } from '@posthog/lemon-ui'
import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'
import React from 'react'

export function AddPersonToChortModalBody(): JSX.Element {
    const { query, cohortPersons } = useValues(addPersonToCohortModalLogic)
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
                    return (
                        <LemonButton
                            type="secondary"
                            status={isInCohort ? 'danger' : 'default'}
                            size="small"
                            onClick={(e) => {
                                e.preventDefault()

                                isInCohort ? null : addPersonToCohort(id)
                            }}
                        >
                            {isInCohort ? <IconMinusSmall /> : <IconPlusSmall />}
                        </LemonButton>
                    )
                },
            },
        },
        showOpenEditorButton: false,
    }
    return (
        <>
            <Query query={query} setQuery={setQuery} context={context} />
        </>
    )
}
