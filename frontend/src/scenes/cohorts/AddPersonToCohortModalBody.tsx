import { useActions, useValues } from 'kea'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { LemonButton } from '@posthog/lemon-ui'
import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'

export function AddPersonToChortModalBody(): JSX.Element {
    const { query } = useValues(addPersonToCohortModalLogic)
    const { setQuery, addPersonToCohort } = useActions(addPersonToCohortModalLogic)
    const context: QueryContext = {
        columns: {
            id: {
                renderTitle: () => null,
                render: (props) => {
                    const id = props.value as string
                    const isInCohort = false
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
