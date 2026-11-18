import { MouseEvent } from 'react'

const INTERACTIVE_SELECTOR = 'a, button, input, label, [role="checkbox"]'

export function isPlainRowClick(event: MouseEvent<HTMLTableRowElement>): boolean {
    const target = event.target
    return target instanceof Element && event.currentTarget.contains(target) && !target.closest(INTERACTIVE_SELECTOR)
}
