import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus } from 'lib/lemon-ui/icons'

export function ActionsList(): JSX.Element {
    const { allActions, sortedActions, allActionsLoading, searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)
    const { newAction } = useActions(actionsTabLogic)

    return (
        <>
            <LemonInput
                autoFocus
                fullWidth
                placeholder="Search"
                type={'search'}
                value={searchTerm}
                className={'mb-1'}
                onChange={(s) => setSearchTerm(s)}
            />
            <div className="actions-list">
                <div className="actions-list-header">
                    <LemonButton type="primary" size="small" onClick={() => newAction()} icon={<IconPlus />}>
                        New action
                    </LemonButton>
                </div>
                {allActions.length === 0 && allActionsLoading ? (
                    <div className="text-center my-4">
                        <Spinner />
                    </div>
                ) : (
                    <ActionsListView actions={sortedActions} />
                )}
            </div>
        </>
    )
}
