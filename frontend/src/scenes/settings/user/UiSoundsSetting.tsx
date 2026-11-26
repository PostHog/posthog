import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { uiSoundsLogic } from 'lib/uiSounds/uiSoundsLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

const LABEL = 'Play button sounds'
// pinned: data-attr value. Renaming it breaks autocapture actions and QA selectors.
const DATA_ATTR = 'ui-sounds-setting'

export function UiSoundsSetting(): JSX.Element {
    const { uiSoundsEnabled } = useValues(uiSoundsLogic)
    const { setUiSoundsEnabled } = useActions(uiSoundsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label={LABEL}
                checked={uiSoundsEnabled}
                onCheckedChange={setUiSoundsEnabled}
                dataAttr={DATA_ATTR}
            />
        )
    }

    return (
        <LemonSwitch
            onChange={setUiSoundsEnabled}
            checked={uiSoundsEnabled}
            label={LABEL}
            data-attr={DATA_ATTR}
            bordered
        />
    )
}
