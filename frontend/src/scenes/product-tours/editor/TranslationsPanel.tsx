import classNames from 'classnames'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCopy, IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { toSentenceCase } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { productTourLogic } from '../productTourLogic'

function LanguageCard({ tourId, langCode }: { tourId: string; langCode: string }): JSX.Element {
    const { productTourForm, selectedLanguage } = useValues(productTourLogic({ id: tourId }))
    const { setSelectedLanguage } = useActions(productTourLogic({ id: tourId }))

    const isActive = langCode === selectedLanguage
    const isDefault = langCode === productTourForm.content.languages?.at(0)

    return (
        <button
            className={classNames(
                'flex p-3 rounded-md bg-surface-primary border border items-center justify-between cursor-pointer',
                isActive && 'border border-accent'
            )}
            role="button"
            onClick={() => setSelectedLanguage(langCode)}
        >
            <div className="flex items-center gap-1">
                <span className="font-mono">{langCode}</span>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconCopy className="w-4 h-4" />}
                    onClick={() => copyToClipboard(langCode, 'language code')}
                />
            </div>
            {isDefault && <LemonTag>Default</LemonTag>}
        </button>
    )
}

function LanguageInput({ tourId }: { tourId: string }): JSX.Element {
    const { productTourForm, entityKeyword } = useValues(productTourLogic({ id: tourId }))
    const { setProductTourFormValue } = useActions(productTourLogic({ id: tourId }))

    const [langInput, setLangInput] = useState('')
    const [langInputError, setLangInputError] = useState<string | undefined>()

    const hasTranslations = (productTourForm.content.languages?.length ?? 0) > 0

    const handleAddLanguage = (): void => {
        if (!langInput?.trim()) {
            setLangInputError('Please enter a language code.')
            return
        }

        let canonical: string
        try {
            const locale = new Intl.Locale(langInput.trim())
            canonical = locale.toString()
        } catch {
            setLangInputError(`'${langInput}' is not a valid BCP 47 language tag (e.g. 'en', 'en-US', 'pt-BR').`)
            return
        }

        if (productTourForm.content.languages?.includes(canonical)) {
            setLangInputError(`Language '${canonical}' already exists for this ${entityKeyword}.`)
            return
        }

        setProductTourFormValue('content', {
            ...productTourForm.content,
            languages: [...(productTourForm.content.languages ?? []), canonical],
        })

        setLangInputError(undefined)
        setLangInput('')
    }

    return (
        <div className="flex flex-col gap-1">
            {hasTranslations && <p className="mb-0 font-medium">Add language</p>}
            <div className="flex gap-2">
                <LemonInput
                    className="font-mono"
                    placeholder="Language code ('en', 'en-US')"
                    fullWidth
                    value={langInput}
                    onChange={setLangInput}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault()
                            handleAddLanguage()
                        }
                    }}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    icon={hasTranslations ? <IconPlus /> : <IconCheck />}
                    onClick={() => handleAddLanguage()}
                />
            </div>
            {langInputError && <p className="text-small text-danger">{langInputError}</p>}
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
                <LanguageInput tourId={tourId} />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {productTourForm.content.languages?.map((lang) => (
                <LanguageCard key={lang} tourId={tourId} langCode={lang} />
            ))}

            <LanguageInput tourId={tourId} />

            <Link to="https://posthog.com/docs/product-tours/localization" target="_blank" targetBlankIcon>
                Read the docs
            </Link>
        </div>
    )
}
