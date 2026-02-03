import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

export function SqlEditorTabPreference(): JSX.Element {
    const { sqlEditorNewTabOpensSearch } = useValues(userPreferencesLogic)
    const { setSqlEditorNewTabOpensSearch } = useActions(userPreferencesLogic)

    return (
        <div>
            <p>
                By default, clicking "New tab" while in the SQL editor opens another SQL editor tab. Enable this option
                to always open the search bar instead.
            </p>
            <LemonSwitch
                label="Open search bar for new tabs in SQL editor"
                data-attr="sql-editor-new-tab-opens-search"
                onChange={(checked) => setSqlEditorNewTabOpensSearch(checked)}
                checked={sqlEditorNewTabOpensSearch}
                bordered
            />
        </div>
    )
}
