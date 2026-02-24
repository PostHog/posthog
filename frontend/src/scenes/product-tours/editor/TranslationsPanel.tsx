import classNames from 'classnames'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { toSentenceCase } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { productTourLogic } from '../productTourLogic'

const COMMON_LANGUAGES: LemonInputSelectOption[] = [
    { key: 'en', label: 'en — English' },
    { key: 'en-US', label: 'en-US — English (US)' },
    { key: 'en-GB', label: 'en-GB — English (UK)' },
    { key: 'es', label: 'es — Spanish' },
    { key: 'es-MX', label: 'es-MX — Spanish (Mexico)' },
    { key: 'fr', label: 'fr — French' },
    { key: 'fr-CA', label: 'fr-CA — French (Canada)' },
    { key: 'de', label: 'de — German' },
    { key: 'it', label: 'it — Italian' },
    { key: 'pt', label: 'pt — Portuguese' },
    { key: 'pt-BR', label: 'pt-BR — Portuguese (Brazil)' },
    { key: 'nl', label: 'nl — Dutch' },
    { key: 'ru', label: 'ru — Russian' },
    { key: 'ja', label: 'ja — Japanese' },
    { key: 'ko', label: 'ko — Korean' },
    { key: 'zh', label: 'zh — Chinese' },
    { key: 'zh-Hans', label: 'zh-Hans — Chinese (Simplified)' },
    { key: 'zh-Hant', label: 'zh-Hant — Chinese (Traditional)' },
    { key: 'ar', label: 'ar — Arabic' },
    { key: 'hi', label: 'hi — Hindi' },
    { key: 'pl', label: 'pl — Polish' },
    { key: 'sv', label: 'sv — Swedish' },
    { key: 'da', label: 'da — Danish' },
    { key: 'fi', label: 'fi — Finnish' },
    { key: 'nb', label: 'nb — Norwegian' },
    { key: 'tr', label: 'tr — Turkish' },
    { key: 'uk', label: 'uk — Ukrainian' },
    { key: 'cs', label: 'cs — Czech' },
    { key: 'el', label: 'el — Greek' },
    { key: 'he', label: 'he — Hebrew' },
    { key: 'th', label: 'th — Thai' },
    { key: 'vi', label: 'vi — Vietnamese' },
    { key: 'id', label: 'id — Indonesian' },
    { key: 'ms', label: 'ms — Malay' },
]

function LanguageCard({ tourId, langCode }: { tourId: string; langCode: string }): JSX.Element {
    const { productTourForm, selectedLanguage } = useValues(productTourLogic({ id: tourId }))
    const { setSelectedLanguage, removeLanguage } = useActions(productTourLogic({ id: tourId }))

    const isActive = langCode === selectedLanguage
    const isDefault = langCode === productTourForm.content.languages?.at(0)

    return (
        <button
            className={classNames(
                'group flex p-3 rounded-md bg-surface-primary border items-center justify-between cursor-pointer',
                isActive ? 'border-accent' : 'border'
            )}
            onClick={() => setSelectedLanguage(langCode)}
        >
            <div className="flex items-center gap-1">
                <span className="font-mono">{langCode}</span>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconCopy className="w-4 h-4" />}
                    onClick={(e) => {
                        e.stopPropagation()
                        void copyToClipboard(langCode, 'language code')
                    }}
                />
            </div>
            <div className="flex items-center gap-1">
                {isDefault && <LemonTag>Default</LemonTag>}
                {!isDefault && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconTrash className="w-4 h-4" />}
                        className="opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => {
                            e.stopPropagation()
                            removeLanguage(langCode)
                        }}
                    />
                )}
            </div>
        </button>
    )
}

function LanguageCombobox({ tourId }: { tourId: string }): JSX.Element {
    const { productTourForm, entityKeyword } = useValues(productTourLogic({ id: tourId }))
    const { setProductTourFormValue } = useActions(productTourLogic({ id: tourId }))

    const [error, setError] = useState<string | undefined>()

    const hasTranslations = (productTourForm.content.languages?.length ?? 0) > 0

    const availableOptions = useMemo(
        () => COMMON_LANGUAGES.filter((opt) => !productTourForm.content.languages?.includes(opt.key)),
        [productTourForm.content.languages]
    )

    const handleChange = (values: string[]): void => {
        const raw = values[0]
        if (!raw) {
            return
        }

        let canonical: string
        try {
            const locale = new Intl.Locale(raw.trim())
            canonical = locale.toString()
        } catch {
            setError(`'${raw}' is not a valid BCP 47 language tag (e.g. 'en', 'en-US', 'pt-BR').`)
            return
        }

        if (productTourForm.content.languages?.includes(canonical)) {
            setError(`Language '${canonical}' already exists for this ${entityKeyword}.`)
            return
        }

        setProductTourFormValue('content', {
            ...productTourForm.content,
            languages: [...(productTourForm.content.languages ?? []), canonical],
        })
        setError(undefined)
    }

    return (
        <div className="flex flex-col gap-1">
            {hasTranslations && <p className="mb-0 font-medium">Add language</p>}
            <LemonInputSelect
                mode="single"
                options={availableOptions}
                value={[]}
                onChange={handleChange}
                allowCustomValues
                placeholder="Search languages or enter a BCP 47 code..."
                fullWidth
                size="small"
                formatCreateLabel={(input) => `Add "${input}"`}
            />
            {error && <p className="text-small text-danger">{error}</p>}
        </div>
    )
}

export function TranslationsPanel({ tourId }: { tourId: string }): JSX.Element {
    const { productTourForm, entityKeyword } = useValues(productTourLogic({ id: tourId }))

    const hasTranslations = (productTourForm.content.languages?.length ?? 0) > 0

    if (!hasTranslations) {
        return (
            <div className="flex flex-col gap-2">
                <p className="text-muted mb-0">
                    Add translations to this {entityKeyword}.{' '}
                    <Link to="https://posthog.com/docs/product-tours/localization" target="_blank" targetBlankIcon>
                        Read the docs
                    </Link>
                </p>
                <p className="mb-0 font-medium">{toSentenceCase(entityKeyword)} default language:</p>
                <LanguageCombobox tourId={tourId} />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {productTourForm.content.languages?.map((lang) => (
                <LanguageCard key={lang} tourId={tourId} langCode={lang} />
            ))}

            <LanguageCombobox tourId={tourId} />

            <Link to="https://posthog.com/docs/product-tours/localization" target="_blank" targetBlankIcon>
                Read the docs
            </Link>
        </div>
    )
}
