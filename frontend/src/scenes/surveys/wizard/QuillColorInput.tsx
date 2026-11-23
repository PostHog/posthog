import { useState } from 'react'

import { Button, Input, Popover, PopoverContent, PopoverTrigger, Text, cn } from '@posthog/quill'

import { colorDescription } from 'lib/lemon-ui/LemonColor/utils'

import { SURVEY_PRESET_COLORS, isCssVariable } from './ColorInput'

function QuillColorSwatch({ color }: { color: string }): JSX.Element {
    const isCssVar = isCssVariable(color)

    return (
        <span
            className={cn(
                'block size-4 shrink-0 rounded-full border border-border',
                isCssVar && 'border-dashed bg-muted'
            )}
            // The swatch shows the user's own color value, so it can't be a token.
            // eslint-disable-next-line react/forbid-dom-props
            style={isCssVar || !color ? undefined : { backgroundColor: color }}
        />
    )
}

export function QuillColorInput({
    id,
    value = '',
    onChange,
    disabled,
    disabledReason,
}: {
    id?: string
    value?: string
    onChange: (value: string) => void
    disabled?: boolean
    disabledReason?: string | null
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <Popover open={isOpen && !disabled} onOpenChange={setIsOpen}>
                    <PopoverTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label="Pick a color"
                                tooltip="Pick a color"
                                disabled={disabled}
                                disabledReason={disabledReason}
                            />
                        }
                    >
                        <QuillColorSwatch color={value} />
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-2">
                        <div className="grid grid-cols-6 gap-1">
                            {SURVEY_PRESET_COLORS.map((color) => (
                                <Button
                                    key={color}
                                    size="icon-sm"
                                    variant={value === color ? 'outline' : 'default'}
                                    aria-label={colorDescription(color)}
                                    aria-pressed={value === color}
                                    tooltip={colorDescription(color)}
                                    onClick={() => {
                                        onChange(color)
                                        setIsOpen(false)
                                    }}
                                >
                                    <QuillColorSwatch color={color} />
                                </Button>
                            ))}
                        </div>
                    </PopoverContent>
                </Popover>
                <Input
                    id={id}
                    className="flex-1 font-mono"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    placeholder="#000000 or var(--color)"
                    disabled={disabled}
                    disabledReason={disabledReason}
                />
            </div>
            {isCssVariable(value) && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    CSS variables won't preview here but will work on your site.
                </Text>
            )}
        </div>
    )
}
