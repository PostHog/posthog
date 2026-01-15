import clsx from 'clsx'

import { IconCheck } from '@posthog/icons'

import { SurveyTheme, surveyThemes } from '../constants'

interface SurveyThemeSelectorProps {
    selectedThemeId: string | null
    onSelectTheme: (theme: SurveyTheme) => void
    disabled?: boolean
}

function ThemePreviewCard({
    theme,
    isSelected,
    onClick,
    disabled,
}: {
    theme: SurveyTheme
    isSelected: boolean
    onClick: () => void
    disabled?: boolean
}): JSX.Element {
    const { appearance } = theme

    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            className={clsx(
                'group relative flex flex-col rounded-lg border-2 p-2 text-left transition-all duration-200',
                'hover:scale-[1.02] active:scale-[0.98]',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
                isSelected
                    ? 'border-primary bg-primary/5 shadow-md'
                    : 'border-border bg-bg-light hover:border-primary/50 hover:shadow-sm',
                disabled && 'cursor-not-allowed opacity-50'
            )}
        >
            {/* Selection indicator */}
            <div
                className={clsx(
                    'absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full transition-all duration-200',
                    isSelected ? 'scale-100 bg-primary' : 'scale-0 bg-transparent'
                )}
            >
                <IconCheck className="h-3 w-3 text-primary-inverse" />
            </div>

            {/* Mini survey preview */}
            <div
                className="mb-1.5 flex h-14 w-full flex-col overflow-hidden rounded border"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: appearance.backgroundColor,
                    borderColor: appearance.borderColor,
                }}
            >
                {/* Header area */}
                <div className="flex items-center gap-1.5 px-2 pt-2">
                    <div
                        className="h-1 w-12 rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: appearance.textColor, opacity: 0.8 }}
                    />
                </div>

                {/* Body - rating buttons preview */}
                <div className="flex flex-1 items-center justify-center gap-1 px-2">
                    {[1, 2, 3, 4, 5].map((i) => (
                        <div
                            key={i}
                            className="h-3 w-3 rounded-sm transition-colors"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                backgroundColor:
                                    i === 4 ? appearance.ratingButtonActiveColor : appearance.ratingButtonColor,
                                border: `1px solid ${appearance.borderColor}`,
                            }}
                        />
                    ))}
                </div>

                {/* Footer - submit button preview */}
                <div className="px-2 pb-2">
                    <div
                        className="h-2.5 w-full rounded"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: appearance.submitButtonColor }}
                    />
                </div>
            </div>

            {/* Theme info */}
            <div className="flex flex-col">
                <span className="text-sm font-medium">{theme.name}</span>
                <span className="text-xs text-muted">{theme.description}</span>
            </div>
        </button>
    )
}

export function SurveyThemeSelector({
    selectedThemeId,
    onSelectTheme,
    disabled,
}: SurveyThemeSelectorProps): JSX.Element {
    return (
        <div className="space-y-2">
            <div>
                <h3 className="font-medium m-0">Choose a theme</h3>
                <p className="text-sm text-muted">Start with a preset and customize colors below</p>
            </div>

            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                {surveyThemes.map((theme) => (
                    <ThemePreviewCard
                        key={theme.id}
                        theme={theme}
                        isSelected={selectedThemeId === theme.id}
                        onClick={() => onSelectTheme(theme)}
                        disabled={disabled}
                    />
                ))}
            </div>
        </div>
    )
}
