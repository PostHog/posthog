import { ToolbarMenu } from '~/toolbar/button/ToolbarMenu'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import clsx from 'clsx'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { ActionsEditingToolbarMenu } from '~/toolbar/actions/ActionsEditingToolbarMenu'
import { Link } from 'lib/lemon-ui/Link'

const ListMenuHeader = (): JSX.Element => {
    const { searchTerm } = useValues(actionsLogic)
    const { setSearchTerm } = useActions(actionsLogic)

    return (
        <>
            <LemonInput
                autoFocus
                fullWidth
                placeholder="Search"
                type={'search'}
                value={searchTerm}
                onChange={(s) => setSearchTerm(s)}
                className={'Toolbar3000__top_input'}
            />
        </>
    )
}

const ListBody = (): JSX.Element => {
    const { newAction } = useActions(actionsTabLogic)
    const { allActions, sortedActions, allActionsLoading } = useValues(actionsLogic)

    return (
        <>
            <div className={clsx('actions-list-header my-2')}>
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
        </>
    )
}

const ListMenuFooter = (): JSX.Element => {
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="w-full text-right">
            <Link to={`${apiURL}${urls.actions()}`} target="_blank">
                View &amp; edit all actions <IconOpenInNew />
            </Link>
        </div>
    )
}

export const ActionsToolbarMenu = (): JSX.Element => {
    const { selectedAction } = useValues(actionsTabLogic)

    return selectedAction ? (
        <ActionsEditingToolbarMenu />
    ) : (
        <ToolbarMenu header={<ListMenuHeader />} body={<ListBody />} footer={<ListMenuFooter />} />
    )
}
