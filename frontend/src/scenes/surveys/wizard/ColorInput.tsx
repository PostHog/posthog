import { useState } from 'react'

import { LemonInput, Popover } from '@posthog/lemon-ui'

import { LemonColorList } from 'lib/lemon-ui/LemonColor'
import { cn } from 'lib/utils/css-classes'

interface ColorInputProps {
    value?: string
    onChange: (value: string) => void
    disabled?: boolean
}

// Survey-appropriate preset colors
const SURVEY_PRESET_COLORS = [
    '#ffffff',
    '#f5f5f5',
    '#e5e5e5',
    '#171717',
    '#000000',
    '#eff6ff',
    '#3b82f6',
    '#1d4ed8',
    '#f0fdf4',
    '#22c55e',
    '#15803d',
    '#fff7ed',
    '#f97316',
    '#c2410c',
    '#faf5ff',
    '#a855f7',
    '#7c3aed',
]

const isCssVariable = (value: string): boolean => {
    return value.trim().startsWith('var(') || value.trim().startsWith('--')
}

// Color glyph that supports any CSS color value
function ColorGlyph({ color }: { color: string }): JSX.Element {
    const isCssVar = isCssVariable(color)

    return (
        <div
            className={cn(
                'relative flex shrink-0 items-center justify-center',
                'w-[22px] h-[22px] rounded-full border-2',
                isCssVar ? 'border-border' : 'border-current'
            )}
            style={
                isCssVar
                    ? {
                          background: 'conic-gradient(from 0deg, #3b82f6, #22c55e, #f97316, #a855f7, #3b82f6)',
                      }
                    : {
                          backgroundColor: color || 'transparent',
                          borderColor: color || 'var(--border)',
                      }
            }
        />
    )
}

export function ColorInput({ value = '', onChange, disabled }: ColorInputProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    const showCssVariableWarning = isCssVariable(value)

    return (
        <div className="space-y-1">
            <div className="flex items-center gap-2">
                <Popover
                    visible={isOpen && !disabled}
                    onClickOutside={() => setIsOpen(false)}
                    overlay={
                        <div className="p-2">
                            <LemonColorList
                                colors={SURVEY_PRESET_COLORS}
                                selectedColor={value}
                                onSelectColor={(color) => {
                                    onChange(color)
                                    setIsOpen(false)
                                }}
                            />
                        </div>
                    }
                >
                    <button
                        type="button"
                        onClick={() => !disabled && setIsOpen(!isOpen)}
                        disabled={disabled}
                        className="shrink-0 p-1 rounded border border-border hover:border-primary/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        <ColorGlyph color={value} />
                    </button>
                </Popover>
                <LemonInput
                    value={value}
                    onChange={onChange}
                    placeholder="#000000 or var(--color)"
                    className="flex-1 font-mono text-xs"
                    size="small"
                    disabled={disabled}
                />
            </div>
            {showCssVariableWarning && (
                <p className="text-xs text-muted m-0">CSS variables won't preview here but will work on your site.</p>
            )}
        </div>
    )
}
