import { IconX } from '@posthog/icons'

// A removable token, not a status badge: one box owns all spacing (the X is a glyph
// in the text flow, not a nested button component), fixed height on the 4px grid,
// optically lighter padding on the icon side.
// `disabledReason` follows the AccessControlAction contract so the chip can be
// wrapped in the same Editor gate as the other prompt actions.
export function PromptLabelChip({
    label,
    onRemove,
    disabledReason,
    'data-attr': dataAttr,
}: {
    label: string
    onRemove?: () => void
    disabled?: boolean
    disabledReason?: string | null
    'data-attr'?: string
}): JSX.Element {
    return (
        <span
            className={`inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-[var(--radius)] border border-[color-mix(in_srgb,var(--purple)_35%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] pl-2 text-[11px] font-medium text-purple ${
                onRemove ? 'pr-1' : 'pr-2'
            }`}
            data-attr={dataAttr}
        >
            {/* Labels can be up to 128 characters; truncate so the remove button stays reachable. */}
            <span className="max-w-40 truncate" title={label}>
                {label}
            </span>
            {onRemove ? (
                <button
                    type="button"
                    aria-label={`Remove label ${label}`}
                    aria-disabled={disabledReason ? true : undefined}
                    title={disabledReason ?? undefined}
                    className={`grid size-3.5 shrink-0 place-items-center rounded-[calc(var(--radius)-2px)] ${
                        disabledReason
                            ? 'cursor-not-allowed opacity-30'
                            : 'cursor-pointer opacity-60 hover:bg-[color-mix(in_srgb,var(--purple)_20%,transparent)] hover:opacity-100'
                    }`}
                    onClick={(e) => {
                        // Chips render inside Link-wrapped cards; removing must not navigate.
                        e.preventDefault()
                        e.stopPropagation()
                        if (!disabledReason) {
                            onRemove()
                        }
                    }}
                >
                    <IconX className="size-3" />
                </button>
            ) : null}
        </span>
    )
}
