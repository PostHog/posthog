import { resolveSettingId } from './SupportSettingsScene'

describe('SupportSettingsScene', () => {
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
})
