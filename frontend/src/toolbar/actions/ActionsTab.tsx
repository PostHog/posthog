import './ActionsTab.scss'

import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { EditAction } from '~/toolbar/actions/EditAction'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import clsx from 'clsx'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'

export function ActionsTab(): JSX.Element {
    const { selectedAction } = useValues(actionsTabLogic)
    const { apiURL } = useValues(toolbarLogic)
    const { hedgehogMode } = useValues(toolbarButtonLogic)

    return (
        <div
            className={clsx(
                'toolbar-block action-block-body ActionsBlockBody justify-between w-full h-full rounded-t',
                hedgehogMode && 'px-2 py-1'
            )}
        >
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
