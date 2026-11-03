import { useActions, useValues } from 'kea'

import { urls } from '~/toolbar/shared/urls'

import { extensionActionsLogic } from '../../logics/panel/extensionActionsLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import { ExtensionEntityList } from '../panel/ExtensionEntityList'

export function ExtensionActionsList(): JSX.Element {
    const { actionsState, filteredActions, searchTerm } = useValues(extensionActionsLogic)
    const { setSearchTerm, selectAction, newAction } = useActions(extensionActionsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)
    const saveResult = actionsState?.saveResult

    return (
        <ExtensionEntityList
            noun="action"
            pluralNoun="actions"
            items={actionsState ? filteredActions : null}
            loading={!!actionsState?.allActionsLoading}
            searchTerm={searchTerm}
            onSearch={setSearchTerm}
            onSelect={selectAction}
            onCreate={() => newAction(false)}
            saved={
                saveResult?.status === 'saved'
                    ? { name: saveResult.name, url: projectUrl(urls.action(saveResult.actionId)) }
                    : null
            }
            viewAllUrl={projectUrl(urls.actions())}
            emptyText="This project has no actions yet."
            hint="The page highlights the elements your actions match. Pick an action to edit it."
            dataAttrs={{
                search: 'toolbar-extension-actions-search',
                row: 'toolbar-extension-action-row',
                create: 'toolbar-extension-new-action',
                openSaved: 'toolbar-extension-open-saved-action',
            }}
        />
    )
}
