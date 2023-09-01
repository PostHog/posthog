import './ActionsTab.scss'

import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { EditAction } from '~/toolbar/actions/EditAction'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

export function ActionsTab(): JSX.Element {
    const { selectedAction } = useValues(actionsTabLogic)
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="toolbar-block action-block-body ActionsBlockBody w-full rounded-t">
            {selectedAction ? (
                <EditAction />
            ) : (
                <>
                    <ActionsList />
                    <div className="text-right mt-4 pr-2">
                        <a href={`${apiURL}${urls.actions()}`} target="_blank" rel="noopener noreferrer">
                            View &amp; edit all actions <IconOpenInNew />
                        </a>
                    </div>
                </>
            )}
        </div>
    )
}
