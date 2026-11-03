import { toSentenceCase } from 'lib/utils/strings'

import type { SettingLevelId } from '~/scenes/settings/types'

export const settingsLevelName = (level: SettingLevelId): string =>
    `${toSentenceCase(level === 'environment' ? 'project' : level)} settings`

export const settingsContextText = (level: SettingLevelId, sectionTitle: string): string =>
    `${settingsLevelName(level)} ${sectionTitle}`

export const sentenceCaseId = (id: string): string => toSentenceCase(id.replace(/-/g, ' '))

export interface SettingSearchTextSetting {
    id: string
    title: string | null
    keywords?: string[]
    description?: string | null
}

export const settingsSearchText = (
    level: SettingLevelId,
    sectionTitle: string,
    sectionKeywords: string[] | undefined,
    settings: SettingSearchTextSetting[]
): string =>
    [
        settingsContextText(level, sectionTitle),
        ...(sectionKeywords ?? []),
        ...settings.flatMap((setting) => [
            setting.title ?? sentenceCaseId(setting.id),
            sentenceCaseId(setting.id),
            ...(setting.keywords ?? []),
            setting.description ?? '',
        ]),
    ]
        .filter(Boolean)
        .join(' ')
