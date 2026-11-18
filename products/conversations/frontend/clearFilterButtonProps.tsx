import { IconChevronDown, IconX } from '@posthog/icons'
import { SideAction } from '@posthog/lemon-ui'

export function clearFilterButtonProps(
    onClear: (() => void) | null,
    tooltip: string
): { sideAction: SideAction; sideIcon?: undefined } | { sideIcon: JSX.Element; sideAction?: undefined } {
    return onClear
        ? {
              sideAction: {
                  icon: <IconX />,
                  tooltip,
                  onClick: (e) => {
                      e.stopPropagation()
                      onClear()
                  },
              },
          }
        : { sideIcon: <IconChevronDown /> }
}
