import { useActions, useValues } from 'kea'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionType } from '~/types'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'

interface ActionsListViewProps {
    actions: ActionType[]
}

export function ActionsListView({ actions }: ActionsListViewProps): JSX.Element {
    const { allActionsLoading, searchTerm } = useValues(actionsLogic)
    const { selectAction } = useActions(actionsTabLogic)
    return (
        <div className={'flex flex-col h-full overflow-y-scoll'}>
            {allActionsLoading ? (
                <div className={'flex items-center'}>
                    <Spinner className={'text-4xl'} />
                </div>
            ) : actions.length ? (
                actions.map((action, index) => (
                    <div
                        key={action.id}
                        className={'flex flex-row gap-2 cursor-pointer py-2 ActionsListItem'}
                        onClick={() => selectAction(action.id || null)}
                    >
                        <span className={'min-w-8 text-right'}>{index + 1}.</span>
                        <span className={'flex-grow'}>
                            {action.name || <span className="italic text-muted-alt">Untitled</span>}
                        </span>
                    </div>
                ))
            ) : (
                <div className={'px-4 py-2'}>No {searchTerm.length ? 'matching ' : ''}actions found.</div>
            )}
        </div>
    )
}
