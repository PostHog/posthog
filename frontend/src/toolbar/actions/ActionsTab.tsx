import './ActionsTab.scss'

import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { EditAction } from '~/toolbar/actions/EditAction'
import { urls } from 'scenes/urls'
import { Link } from '@posthog/lemon-ui'

export function ActionsTab(): JSX.Element {
    const { selectedAction } = useValues(actionsTabLogic)
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="toolbar-content">
            <div className="toolbar-block action-block-body p-2 pt-3">
                {selectedAction ? (
                    <EditAction />
                ) : (
                    <>
                        <ActionsList />
                        <div className="text-right mt-4">
                            <Link to={`${apiURL}${urls.actions()}`} target="_blank" targetBlankIcon>
                                View &amp; edit all actions
                            </Link>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
