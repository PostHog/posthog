import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonButton } from '@posthog/lemon-ui'

export function ActionsList(): JSX.Element {
    const { allActions, sortedActions, allActionsLoading, searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)
    const { newAction } = useActions(actionsTabLogic)

    return (
        <>
            <LemonInput
                autoFocus
                placeholder="Search"
                type={'search'}
                fullWidth
                value={searchTerm}
                onChange={(s) => setSearchTerm(s)}
            />
            <div className="actions-list">
                <div className="actions-list-header flex-flex-row">
                    <LemonButton type="primary" size="small" icon={<PlusOutlined />} onClick={() => newAction()}>
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
