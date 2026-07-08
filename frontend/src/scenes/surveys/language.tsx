import { COUNTRY_CODE_TO_LONG_NAME, LANGUAGE_CODE_TO_NAME } from 'lib/utils/country'

import { Survey } from '~/types'

export const DEFAULT_SURVEY_BASE_LANGUAGE = 'en'

// Lightweight frontend shape check for BCP-47 codes — inline UX only.
// The backend is the source of truth and will return a clear error if its rules diverge.
const BCP47_LANGUAGE_CODE_RE = /^[a-z]{2,3}(-[a-z0-9]{2,8}){0,3}$/

export const COMMON_SURVEY_LANGUAGE_CODES = [
    'en',
    'en-US',
    'en-GB',
    'es',
    'es-ES',
    'es-MX',
    'fr',
    'fr-FR',
    'fr-CA',
    'de',
    'de-DE',
    'ar',
    'bg',
    'bn',
    'ca',
    'cs',
    'da',
    'el',
    'et',
    'fa',
    'fi',
    'he',
    'hi',
    'hr',
    'hu',
    'id',
    'it',
    'ja',
    'ko',
    'lt',
    'lv',
    'ms',
    'nl',
    'no',
    'pl',
    'pt',
    'pt-BR',
    'pt-PT',
    'ro',
    'ro-RO',
    'ru',
    'sk',
    'sl',
    'sr',
    'sv',
    'th',
    'tr',
    'uk',
    'ur',
    'vi',
    'zh',
    'zh-CN',
    'zh-TW',
]

const REGION_DISPLAY_NAME_OVERRIDES: Record<string, string> = {
    CN: 'Simplified',
    GB: 'UK',
    TW: 'Traditional',
    US: 'US',
}

export function normalizeLanguageCode(raw: string): string {
    return raw.trim().toLowerCase().replace(/_/g, '-')
}

export function isValidLanguageCode(raw: string): boolean {
    if (!raw) {
        return false
    }
    return BCP47_LANGUAGE_CODE_RE.test(normalizeLanguageCode(raw))
}

export function getSurveyLanguageLabel(languageCode: string): string {
    const hyphenIndex = languageCode.indexOf('-')
    if (hyphenIndex === -1) {
        const languageName = LANGUAGE_CODE_TO_NAME[languageCode] ?? languageCode
        return `${languageName} (${languageCode})`
    }
    const baseLanguageCode = languageCode.substring(0, hyphenIndex)
    const regionCode = languageCode.substring(hyphenIndex + 1)

    const languageName = LANGUAGE_CODE_TO_NAME[baseLanguageCode] ?? baseLanguageCode

    if (!regionCode) {
        return `${languageName} (${languageCode})`
    }

    const normalizedRegionCode = regionCode.toUpperCase()
    const regionName =
        REGION_DISPLAY_NAME_OVERRIDES[normalizedRegionCode] ??
        COUNTRY_CODE_TO_LONG_NAME[normalizedRegionCode] ??
        regionCode

    return `${languageName} - ${regionName} (${languageCode})`
}

export function getSurveyLanguageName(languageCode: string): string {
    return getSurveyLanguageLabel(languageCode).replace(/\s*\([^)]*\)\s*$/, '')
}

export const COMMON_LANGUAGES = COMMON_SURVEY_LANGUAGE_CODES.map((languageCode) => ({
    value: languageCode,
    label: getSurveyLanguageLabel(languageCode),
}))

/**
 * Split a list of translation keys into ones the SDK can resolve and "legacy" entries
 * (non-canonical aliases, sentinels, or collisions with the survey's base language).
 */
export function classifyTranslationKeys(
    keys: string[],
    baseLanguage: string
): { validKeys: string[]; invalidKeys: string[] } {
    const validKeys: string[] = []
    const invalidKeys: string[] = []
    const normalizedBase = normalizeLanguageCode(baseLanguage)
    for (const key of keys) {
        const normalized = normalizeLanguageCode(key)
        if (!isValidLanguageCode(key) || normalized === normalizedBase) {
            invalidKeys.push(key)
        } else {
            validKeys.push(key)
        }
    }
    return { validKeys, invalidKeys }
}

export function getBaseLanguage(survey: Pick<Survey, 'base_language'> | null | undefined): string {
    const raw = survey?.base_language
    if (typeof raw === 'string' && raw.trim()) {
        return normalizeLanguageCode(raw)
    }
    return DEFAULT_SURVEY_BASE_LANGUAGE
}

export function describeInvalidLanguageCode(raw: string, baseLanguage: string): string | null {
    if (!raw || !raw.trim()) {
        return 'Pick a language to add.'
    }
    if (!isValidLanguageCode(raw)) {
        return `"${raw}" isn't a valid language code. Use codes like "en", "es", or "es-MX".`
    }
    if (normalizeLanguageCode(raw) === normalizeLanguageCode(baseLanguage)) {
        return `"${raw}" matches the survey's original language. Change the original first, or translate to a different language.`
    }
    return null
}
