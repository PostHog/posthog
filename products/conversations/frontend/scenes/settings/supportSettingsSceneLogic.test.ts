import { router } from 'kea-router'

import { settingsLogic } from 'scenes/settings/settingsLogic'

import { initKeaTests } from '~/test/init'

import { CONVERSATIONS_LOGIC_KEY, supportSettingsSceneLogic } from './supportSettingsSceneLogic'

describe('supportSettingsSceneLogic', () => {
    it('drops the channel from the URL when another section is selected', () => {
        initKeaTests()
        router.actions.push('/support/settings', {}, { selectedSetting: 'conversations-channels', channel: 'email' })
        const settings = settingsLogic({ logicKey: CONVERSATIONS_LOGIC_KEY, sectionId: 'environment-conversations' })
        settings.mount()
        supportSettingsSceneLogic.mount()

        settings.actions.selectSetting('conversations-general')

        expect(router.values.hashParams).toEqual({ selectedSetting: 'conversations-general' })
    })
})
