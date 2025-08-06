import { useActions, useValues } from 'kea'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { IconPlusSmall } from '@posthog/icons'
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
                    if (isInCohort) {
                        return <LemonTag type="success">Added</LemonTag>
                    }
                    return (
                        <LemonButton
                            type="secondary"
                            status="default"
                            size="small"
                            onClick={(e) => {
                                e.preventDefault()
                                addPersonToCohort(id)
                            }}
                        >
                            <IconPlusSmall />
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
