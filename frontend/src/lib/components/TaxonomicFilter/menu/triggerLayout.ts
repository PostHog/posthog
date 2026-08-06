import { cn } from '@posthog/quill'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'

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
 *
 * `CLICK_OUTSIDE_BLOCK_CLASS` keeps a picker usable when it's rendered inside
 * another Lemon `Popover` (a `More` menu, a column header dropdown). Without
 * it the trigger click bubbles to the parent overlay's `onClickInside`, which
 * closes the parent and unmounts the picker before it can open. The legacy
 * path got this for free — its nested `LemonDropdown` stops propagation when
 * it detects a parent popover — but the rebuilt trigger is a plain button.
 */
export function taxonomicTriggerWrapperClassName(fullWidth?: boolean): string {
    return cn('relative flex min-w-0', CLICK_OUTSIDE_BLOCK_CLASS, fullWidth ? 'w-full' : 'max-w-full')
}
