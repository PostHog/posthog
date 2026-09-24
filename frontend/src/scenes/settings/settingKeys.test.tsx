import { getSettingKeys } from './settingKeys'
import { Setting, SettingId } from './types'

describe('getSettingKeys', () => {
    const setting = (id: string): Setting => ({ id: id as SettingId, title: id, component: <></> })

    it('keeps a setting on the same key when an earlier setting is filtered out', () => {
        const all = [setting('project-details'), setting('project-product-description'), setting('project-danger-zone')]
        const withoutFlagGatedSetting = [all[0], all[2]]

        expect(getSettingKeys(all)[2]).toEqual(getSettingKeys(withoutFlagGatedSetting)[1])
    })

    it('gives repeated setting ids distinct keys', () => {
        expect(getSettingKeys([setting('group-analytics'), setting('group-analytics')])).toEqual([
            'group-analytics',
            'group-analytics-1',
        ])
    })
})
