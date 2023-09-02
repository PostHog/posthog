import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { IconPlus } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'

export function ActionsList(): JSX.Element {
    const { allActions, sortedActions, allActionsLoading, searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)
    const { newAction } = useActions(actionsTabLogic)
    const { hedgehogMode } = useValues(toolbarButtonLogic)

    return (
        <>
            <LemonInput
                autoFocus
                fullWidth
                placeholder="Search"
                type={'search'}
                value={searchTerm}
                className={clsx('mb-1', !hedgehogMode && 'rounded-b-0')}
                onChange={(s) => setSearchTerm(s)}
            />
            <div className="actions-list h-full overflow-hidden">
                <div className={clsx('actions-list-header pt-2 pb-4', !hedgehogMode && 'px-2')}>
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
