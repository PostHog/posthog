import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { ActionsEditingToolbarMenu } from '~/toolbar/actions/ActionsEditingToolbarMenu'
import { Link } from 'lib/lemon-ui/Link'

const ActionsListToolbarMenu = (): JSX.Element => {
    const { searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)

    const { newAction } = useActions(actionsTabLogic)
    const { allActions, sortedActions, allActionsLoading } = useValues(actionsLogic)

    const { apiURL } = useValues(toolbarConfigLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput
                    autoFocus
                    fullWidth
                    placeholder="Search"
                    type={'search'}
                    value={searchTerm}
                    onChange={(s) => setSearchTerm(s)}
                    className={'Toolbar__top_input'}
                />
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="px-1 space-y-px py-2">
                    {allActions.length === 0 && allActionsLoading ? (
                        <div className="text-center my-4">
                            <Spinner />
                        </div>
                    ) : (
                        <ActionsListView actions={sortedActions} />
                    )}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <div className="flex items-center justify-between flex-1">
                    <LemonButton type="primary" size="small" onClick={() => newAction()} icon={<IconPlus />}>
                        New action
                    </LemonButton>
                    <Link to={`${apiURL}${urls.actions()}`} target="_blank">
                        View &amp; edit all actions <IconOpenInNew />
                    </Link>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}

export const ActionsToolbarMenu = (): JSX.Element => {
    const { selectedAction } = useValues(actionsTabLogic)
    return selectedAction ? <ActionsEditingToolbarMenu /> : <ActionsListToolbarMenu />
}
