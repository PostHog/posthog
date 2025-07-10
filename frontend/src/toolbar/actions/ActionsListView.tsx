import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { Link } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionType } from '~/types'

interface ActionsListViewProps {
    actions: ActionType[]
}

export function ActionsListView({ actions }: ActionsListViewProps): JSX.Element {
    const { allActionsLoading, searchTerm } = useValues(actionsLogic)
    const { selectAction } = useActions(actionsTabLogic)

    return (
        <div className="deprecated-space-y-px mb-2 flex h-full flex-col overflow-y-auto">
            {actions.length ? (
                actions.map((action, index) => (
                    <Fragment key={action.id}>
                        <Link
                            subtle
                            onClick={() => selectAction(action.id || null)}
                            className="my-1 w-full font-medium"
                        >
                            <span className="inline-block min-w-[2rem] text-left">{index + 1}.</span>
                            <span className="flex-grow">
                                {action.name || <span className="text-secondary italic">Untitled</span>}
                            </span>
                        </Link>
                    </Fragment>
                ))
            ) : allActionsLoading ? (
                <div className="flex items-center">
                    <Spinner className="text-4xl" />
                </div>
            ) : (
                <div className="p-2">No {searchTerm.length ? 'matching ' : ''}actions found.</div>
            )}
        </div>
    )
}
