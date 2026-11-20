import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { userLogic } from 'scenes/userLogic'

export function OptOutCapture(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => updateUser({ anonymize_data: checked })

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Anonymize my data"
                dataAttr="anonymize-data-collection"
                checked={user?.anonymize_data ?? false}
                onCheckedChange={handleChange}
                disabled={userLoading}
            />
        )
    }

    return (
        <div>
            <LemonSwitch
                label="Anonymize my data"
                data-attr="anonymize-data-collection"
                onChange={handleChange}
                checked={user?.anonymize_data ?? false}
                disabled={userLoading}
                bordered
            />
        </div>
    )
}
