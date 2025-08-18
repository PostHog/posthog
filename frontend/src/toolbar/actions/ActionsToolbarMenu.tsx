import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ActionsEditingToolbarMenu } from '~/toolbar/actions/ActionsEditingToolbarMenu'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

const ActionsListToolbarMenu = (): JSX.Element => {
    const { searchTerm } = useValues(actionsLogic)
    const { setSearchTerm, getActions } = useActions(actionsLogic)

    const { newAction } = useActions(actionsTabLogic)
    const { allActions, sortedActions, allActionsLoading } = useValues(actionsLogic)

    const { apiURL } = useValues(toolbarConfigLogic)

    useOnMountEffect(getActions)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput
                    autoFocus={true}
                    fullWidth={true}
                    placeholder="Search"
                    type="search"
                    value={searchTerm}
                    onChange={(s) => setSearchTerm(s)}
                />
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="px-1 deprecated-space-y-px py-2">
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
                    <Link to={`${apiURL}${urls.actions()}`} target="_blank" className="text-primary">
                        View &amp; edit all actions <IconOpenInNew />
                    </Link>
                    <LemonButton type="primary" size="small" onClick={() => newAction()} icon={<IconPlus />}>
                        New action
                    </LemonButton>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}

export const ActionsToolbarMenu = (): JSX.Element => {
    const { selectedAction } = useValues(actionsTabLogic)
    return selectedAction ? <ActionsEditingToolbarMenu /> : <ActionsListToolbarMenu />
}
