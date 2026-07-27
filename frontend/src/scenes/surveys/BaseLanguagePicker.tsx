import { useMemo, useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInputSelect, Popover } from '@posthog/lemon-ui'

import { COMMON_LANGUAGES, isValidLanguageCode, normalizeLanguageCode } from './language'

interface BaseLanguagePickerProps {
    baseLanguage: string
    onChange: (next: string) => void
    /** Languages already present as translations — filtered out of the picker to avoid collisions. */
    translatedLanguages?: string[]
}

export function BaseLanguagePicker({
    baseLanguage,
    onChange,
    translatedLanguages = [],
}: BaseLanguagePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const normalizedTranslated = useMemo(
        () => new Set(translatedLanguages.map(normalizeLanguageCode)),
        [translatedLanguages]
    )

    const options = useMemo(
        () =>
            COMMON_LANGUAGES.filter((language) => !normalizedTranslated.has(normalizeLanguageCode(language.value))).map(
                (language) => ({ key: language.value, label: language.label })
            ),
        [normalizedTranslated]
    )

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="flex flex-col gap-2 p-2 w-72">
                    <p className="text-sm text-muted">
                        Pick the language the survey is written in. Translations to this language aren't allowed — the
                        original already covers it.
                    </p>
                    <LemonInputSelect
                        mode="single"
                        options={options}
                        value={[baseLanguage]}
                        onChange={(values) => {
                            const lang = values[0]
                            if (lang && isValidLanguageCode(lang)) {
                                onChange(normalizeLanguageCode(lang))
                                setOpen(false)
                            }
                        }}
                        placeholder="Search languages"
                        data-attr="survey-base-language-select"
                    />
                </div>
            }
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconPencil />}
                onClick={() => setOpen((v) => !v)}
                tooltip="Change the survey's original language"
                data-attr="survey-base-language-change"
            >
                Change
            </LemonButton>
        </Popover>
    )
}
