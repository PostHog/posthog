import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'

export function SqlEditorTabPreference(): JSX.Element {
    const { sqlEditorNewTabPreference } = useValues(userPreferencesLogic)
    const { setSqlEditorNewTabPreference } = useActions(userPreferencesLogic)

    return (
        <div>
            <p>
                By default, clicking "New tab" while in the SQL editor opens another SQL editor tab. If you prefer,
                clicking "New tab" can open the PostHog search command (which has access to other apps, recent tabs,
                etc.) instead.
            </p>
            <LemonSelect
                value={sqlEditorNewTabPreference}
                onChange={setSqlEditorNewTabPreference}
                options={[
                    { value: 'editor', label: 'Open a new SQL editor tab' },
                    { value: 'search', label: 'Open the search command' },
                ]}
            />
        </div>
    )
}
