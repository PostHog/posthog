import { Page } from '@playwright/test'
import { SettingId, SettingLevelId, SettingSectionId } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

import { setLemonSwitchValue } from './utils'

export class SettingsPage {
    readonly page: Page

    constructor(page: Page) {
        this.page = page
    }

    async goTo(section?: SettingSectionId | SettingLevelId, setting?: SettingId): Promise<SettingsPage> {
        await this.page.goto(urls.settings(section, setting))
        return this
    }

    async setTestAccountFilter(value: boolean): Promise<void> {
        await this.goTo('project-product-analytics', 'internal-user-filtering')
        await setLemonSwitchValue(this.page, 'Enable this filter on all new insights', value)
    }
}
