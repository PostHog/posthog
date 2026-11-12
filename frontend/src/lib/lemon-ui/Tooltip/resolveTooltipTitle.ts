import type { TooltipTitle } from './Tooltip'

export function resolveTooltipTitle(title: TooltipTitle): React.ReactNode {
    return typeof title === 'function' ? title() : title
}
