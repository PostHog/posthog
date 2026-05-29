import { useActions, useValues } from 'kea'

import { Popover, Spinner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { MAX_TRANSLATE_LENGTH, SUPPORTED_LANGUAGES, messageActionsMenuLogic } from './messageActionsMenuLogic'

export interface TranslatePopoverProps {
    content: string
    title?: string
}

export function TranslatePopover({ content, title = 'Translate' }: TranslatePopoverProps): JSX.Element {
    const logic = messageActionsMenuLogic({ content })
    const {
        showTranslatePopover,
        targetLanguage,
        translation,
        translationLoading,
        translationError,
        isTooLong,
        currentLanguageLabel,
    } = useValues(logic)
    const { setShowTranslatePopover, setTargetLanguage, translate } = useActions(logic)

    const translationText = translation?.translation
    const isTranslatedForCurrentLanguage = translation?.targetLanguage === targetLanguage

    return (
        <Popover
            visible={showTranslatePopover}
            onClickOutside={() => setShowTranslatePopover(false)}
            placement="bottom"
            overlay={
                <div className="p-3 min-w-72 max-w-120">
                    <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-sm">{title}</span>
                        <LemonButton
                            size="xsmall"
                            onClick={() => setShowTranslatePopover(false)}
                            noPadding
                            data-attr="llma-translate-close"
                        >
                            <span className="text-lg leading-none">&times;</span>
                        </LemonButton>
                    </div>
                    <div className="border-t pt-3">
                        {isTooLong ? (
                            <div className="text-xs text-warning mb-2">
                                Text truncated to {MAX_TRANSLATE_LENGTH.toLocaleString()} characters for translation
                            </div>
                        ) : null}
                        <div className="flex items-center gap-2 mb-3">
                            <span className="text-sm text-muted">To:</span>
                            <LemonSelect
                                size="small"
                                value={targetLanguage}
                                onChange={(value) => value && setTargetLanguage(value)}
                                options={SUPPORTED_LANGUAGES.map((lang) => ({
                                    value: lang.value,
                                    label: lang.label,
                                }))}
                                data-attr="llma-translate-language-select"
                            />
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={translate}
                                loading={translationLoading}
                                data-attr="llma-translate-submit"
                            >
                                {translationText && isTranslatedForCurrentLanguage ? 'Re-translate' : 'Translate'}
                            </LemonButton>
                        </div>
                        {translationLoading ? (
                            <div className="flex items-center justify-center py-4 gap-2">
                                <Spinner className="text-lg" />
                                <span className="text-muted">Translating to {currentLanguageLabel}...</span>
                            </div>
                        ) : translationError ? (
                            <div className="text-center py-2">
                                <p className="text-danger mb-2">Translation failed. Please try again.</p>
                            </div>
                        ) : translationText ? (
                            <div className="whitespace-pre-wrap text-sm bg-bg-light rounded p-2 max-h-80 overflow-y-auto">
                                {translationText}
                            </div>
                        ) : (
                            <div className="text-center py-4 text-muted text-sm">
                                Select a language and click Translate
                            </div>
                        )}
                    </div>
                </div>
            }
        >
            <span />
        </Popover>
    )
}
