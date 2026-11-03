import { toSentenceCase } from 'lib/utils/strings'

import type { SettingLevelId } from '~/scenes/settings/types'

export const settingsLevelName = (level: SettingLevelId): string =>
    `${toSentenceCase(level === 'environment' ? 'project' : level)} settings`

export const settingsContextText = (level: SettingLevelId, sectionTitle: string): string =>
    `${settingsLevelName(level)} ${sectionTitle}`
