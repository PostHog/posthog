import { cn } from '@posthog/quill'

/**
 * Single source of truth for the layout of any taxonomic-filter trigger
 * wrapper — the legacy `TaxonomicPopover` fallback, the lazy placeholder
 * before the rebuilt menu mounts, and the rebuilt `TaxonomicFilterMenu`
 * itself. Keeping them identical means swapping between the legacy and
 * rebuilt triggers (or the placeholder → armed transition) never shifts the
 * trigger's box.
 *
 * `relative` anchors the floating `<TaxonomicMenuToggle>`; `flex min-w-0`
 * (not `inline-flex`) lets the trigger fill its parent column and truncate
 * instead of sizing to its intrinsic width; width tracks the call site's
 * `fullWidth` so a full-width column stays full width in every variant.
 */
export function taxonomicTriggerWrapperClassName(fullWidth?: boolean): string {
    return cn('relative flex min-w-0', fullWidth ? 'w-full' : 'max-w-full')
}
