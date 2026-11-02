import { useState } from 'react'

import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    MenuLabel,
} from '@posthog/quill'

import { type ModeChoice, type ModeValue, useModeSelector } from './ModeSelector'

const AUTO_MODE_KEY = '__auto__'

function toMenuValue(value: ModeValue): string {
    return value ?? AUTO_MODE_KEY
}

function fromMenuValue(value: string): ModeValue {
    return value === AUTO_MODE_KEY ? null : (value as ModeValue)
}

/**
 * The legacy chat's agent mode selector in the quill composer: the same choices as the lemon
 * `ModeSelector`, as a quill dropdown of radio rows; each row's tooltip carries the mode's description.
 */
export function QuillModeSelector(): JSX.Element {
    const [open, setOpen] = useState(false)
    const { value, sections, disabledReason, onChange } = useModeSelector()
    const choices = sections.flatMap((section) => section.options)
    const selected: ModeChoice | undefined = choices.find((choice) => choice.value === value) ?? choices[0]

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger
                render={
                    <Button
                        type="button"
                        variant="default"
                        size="sm"
                        aria-label="Mode"
                        tooltip="Select a mode to focus PostHog AI on a specific product or task."
                        disabledReason={disabledReason}
                        data-attr="max-mode-selector"
                    >
                        {selected?.icon}
                        <span className="@max-[400px]/composer:max-w-20 truncate">{selected?.name ?? 'Mode'}</span>
                    </Button>
                }
            />
            <DropdownMenuContent align="start" side="top" sideOffset={6} className="min-w-[220px]">
                <MenuLabel>Mode</MenuLabel>
                <DropdownMenuRadioGroup
                    value={toMenuValue(value)}
                    // Applied on pick, not after the menu closes, so a message sent during the close runs in the new mode.
                    onValueChange={(next) => {
                        onChange(fromMenuValue(next))
                        setOpen(false)
                    }}
                >
                    {sections.map((section, index) => (
                        <div key={index}>
                            {index > 0 && <DropdownMenuSeparator />}
                            {section.options.map((choice) => (
                                <DropdownMenuRadioItem
                                    key={toMenuValue(choice.value)}
                                    value={toMenuValue(choice.value)}
                                    tooltip={choice.description}
                                    data-attr={`max-mode-${toMenuValue(choice.value)}`}
                                >
                                    {choice.icon}
                                    <span className="whitespace-nowrap">{choice.name}</span>
                                    {choice.beta && <Badge variant="warning">Beta</Badge>}
                                    {choice.alpha && <Badge variant="destructive">Alpha</Badge>}
                                </DropdownMenuRadioItem>
                            ))}
                        </div>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
