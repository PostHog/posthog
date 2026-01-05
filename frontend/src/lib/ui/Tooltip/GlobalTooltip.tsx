import { Tooltip } from '@base-ui/react/tooltip'
import { Side } from '@base-ui/react/utils/useAnchorPositioning'
import { PropsWithChildren } from 'react'

import { AppShortcutProps } from 'lib/components/AppShortcuts/AppShortcut'

import { KeyboardShortcutsFromKeybind } from '~/layout/navigation-3000/components/KeyboardShortcut'

export type TooltipPayload = {
    side?: Side
    title: React.ReactNode
    content?: React.ReactNode
    keyboardShortcut?: AppShortcutProps['keybind']
}
export const tooltipHandle = Tooltip.createHandle<TooltipPayload>()

function GlobalTooltip(): JSX.Element {
    return (
        <Tooltip.Root handle={tooltipHandle}>
            {({ payload }) => {
                return (
                    <Tooltip.Portal>
                        <Tooltip.Positioner
                            sideOffset={10}
                            side={payload?.side ?? 'top'}
                            className="
                      h-(--positioner-height) w-(--positioner-width)
                      max-w-(--available-width)
                      data-instant:transition-none"
                        >
                            <Tooltip.Popup
                                className="
                          relative
                          h-(--popup-height,auto) w-(--popup-width,auto)
                          max-w-[500px]
                          rounded-md
                          bg-surface-tooltip
                          text-primary-inverse
                          px-2 py-1
                          origin-(--transform-origin)
                          shadow-lg shadow-gray-200 outline-1 outline-gray-200
                          data-ending-style:opacity-0 data-ending-style:scale-90
                          data-instant:transition-none
                          data-starting-style:opacity-0 data-starting-style:scale-90
                          dark:shadow-none dark:outline-gray-300 dark:-outline-offset-1"
                            >
                                {payload !== undefined && (
                                    <div className="flex flex-col gap-1">
                                        {payload.title && (
                                            <TooltipTitle>
                                                {payload.title}{' '}
                                                {payload.keyboardShortcut && (
                                                    <KeyboardShortcutsFromKeybind keybind={payload.keyboardShortcut} />
                                                )}
                                            </TooltipTitle>
                                        )}
                                        {payload.content && <TooltipContent>{payload.content}</TooltipContent>}
                                    </div>
                                )}
                            </Tooltip.Popup>
                        </Tooltip.Positioner>
                    </Tooltip.Portal>
                )
            }}
        </Tooltip.Root>
    )
}

function TooltipTitle({ children }: PropsWithChildren<Record<never, any>>): JSX.Element {
    return <span className="text-xs">{children}</span>
}

function TooltipContent({ children }: PropsWithChildren<Record<never, any>>): JSX.Element {
    return <span className="text-xs">{children}</span>
}

export { GlobalTooltip, TooltipTitle, TooltipContent }
