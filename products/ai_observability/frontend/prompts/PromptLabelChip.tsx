import { IconX } from '@posthog/icons'

// A removable token, not a status badge: one box owns all spacing (the X is a glyph
// in the text flow, not a nested button component), fixed height on the 4px grid,
// optically lighter padding on the icon side.
export function PromptLabelChip({
    label,
    onRemove,
    'data-attr': dataAttr,
}: {
    label: string
    onRemove?: () => void
    'data-attr'?: string
}): JSX.Element {
    return (
        <span
            className={`inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-[var(--radius)] border border-[color-mix(in_srgb,var(--purple)_35%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] pl-2 text-[11px] font-medium text-purple ${
                onRemove ? 'pr-1' : 'pr-2'
            }`}
            data-attr={dataAttr}
        >
            {label}
            {onRemove ? (
                <button
                    type="button"
                    aria-label={`Remove label ${label}`}
                    className="grid size-3.5 shrink-0 cursor-pointer place-items-center rounded-[calc(var(--radius)-2px)] opacity-60 hover:bg-[color-mix(in_srgb,var(--purple)_20%,transparent)] hover:opacity-100"
                    onClick={(e) => {
                        // Chips render inside Link-wrapped cards; removing must not navigate.
                        e.preventDefault()
                        e.stopPropagation()
                        onRemove()
                    }}
                >
                    <IconX className="size-3" />
                </button>
            ) : null}
        </span>
    )
}
