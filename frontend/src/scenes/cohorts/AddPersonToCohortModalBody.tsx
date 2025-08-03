import { useActions, useValues } from 'kea'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'
import { LemonButton } from '@posthog/lemon-ui'
import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'

export function AddPersonToChortModalBody(): JSX.Element {
    const { query } = useValues(addPersonToCohortModalLogic)
    const { setQuery } = useActions(addPersonToCohortModalLogic)
    const context: QueryContext = {
        columns: {
            id: {
                render: () => {
                    const isInCohort = false
                    return (
                        <LemonButton
                            type="secondary"
                            status={isInCohort ? 'danger' : 'default'}
                            size="small"
                            fullWidth
                            onClick={(e) => {
                                e.preventDefault()

                                // isInCohort
                                //     ? removeInsightFromDashboard(insight, dashboard?.id || 0)
                                //     : addInsightToDashboard(insight, dashboard?.id || 0)
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
