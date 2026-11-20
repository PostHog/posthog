import { router } from 'kea-router'

import { settingsLogic } from 'scenes/settings/settingsLogic'
import { urls } from 'scenes/urls'

import { CONVERSATIONS_LOGIC_KEY } from './supportSettingsSceneLogic'

export type ChannelTabKey = 'widget' | 'email' | 'slack' | 'teams' | 'github' | 'api'

export function openChannelSettings(channel: ChannelTabKey): void {
    // Switch the embedded settings pane via its own logic — settingsLogic does not
    // sync selectedSetting from /support/settings hash changes.
    settingsLogic({
        logicKey: CONVERSATIONS_LOGIC_KEY,
        sectionId: 'environment-conversations',
    }).actions.selectSetting('conversations-channels')
    router.actions.push(urls.supportSettings(), router.values.searchParams, {
        ...router.values.hashParams,
        selectedSetting: 'conversations-channels',
        channel,
    })
}
