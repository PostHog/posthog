import { router } from 'kea-router'

import { settingsLogic } from 'scenes/settings/settingsLogic'

import { initKeaTests } from '~/test/init'

import { CONVERSATIONS_LOGIC_KEY, resolveSettingId, supportSettingsSceneLogic } from './supportSettingsSceneLogic'

describe('supportSettingsSceneLogic', () => {
    test.each([
        ['no hash', {}, 'conversations-general'],
        ['a channel deep link without a section', { channel: 'email' }, 'conversations-channels'],
        [
            'a link that selects General with a channel',
            { selectedSetting: 'conversations-general', channel: 'email' },
            'conversations-channels',
        ],
        ['the channels section', { selectedSetting: 'conversations-channels' }, 'conversations-channels'],
        [
            'a section with a leftover channel',
            { selectedSetting: 'conversations-macros', channel: 'email' },
            'conversations-macros',
        ],
        ['an unknown section', { selectedSetting: 'not-a-setting' }, 'conversations-general'],
    ])('resolves %s', (_name, hashParams, expected) => {
        expect(resolveSettingId(hashParams)).toBe(expected)
    })

    it('opens the section from the URL when the scene mounts first', () => {
        initKeaTests()
        router.actions.push('/support/settings', {}, { channel: 'email' })
        supportSettingsSceneLogic.mount()

        const settings = settingsLogic({ logicKey: CONVERSATIONS_LOGIC_KEY, sectionId: 'environment-conversations' })

        expect(settings.values.selectedSettingId).toBe('conversations-channels')
    })

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
