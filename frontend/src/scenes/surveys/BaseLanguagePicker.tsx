import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInputSelect, Popover } from '@posthog/lemon-ui'

import { COMMON_LANGUAGES, isValidLanguageCode, normalizeLanguageCode } from './language'

interface BaseLanguagePickerProps {
    baseLanguage: string
    onChange: (next: string) => void
}

export function BaseLanguagePicker({ baseLanguage, onChange }: BaseLanguagePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
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
                        options={COMMON_LANGUAGES.map((l) => ({ key: l.value, label: l.label }))}
                        value={[baseLanguage]}
                        onChange={(values) => {
                            const lang = values[0]
                            if (lang && isValidLanguageCode(lang)) {
                                onChange(normalizeLanguageCode(lang))
                                setOpen(false)
                            }
                        }}
                        placeholder="Search languages"
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
            >
                Change
            </LemonButton>
        </Popover>
    )
}
