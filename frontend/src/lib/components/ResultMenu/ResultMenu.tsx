import './ResultMenu.scss'

import { KeyboardEvent, MouseEvent, ReactNode, useCallback, useRef } from 'react'

import { LemonButton, Popover } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface ResultMenuAction {
    name: string
    icon: ReactNode
    className: string
    disabledReason?: string
    onClick: () => void
    to?: string
    inPlace?: boolean
}

export function ResultMenu({
    selectedResult,
    caption,
    interaction,
    actions,
    canFilter = false,
    close,
}: {
    selectedResult: ReactNode
    caption: string
    interaction: { x: number; y: number; timestamp?: number } | null
    actions: ResultMenuAction[]
    canFilter?: boolean
    close: () => void
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const previousFocus = useRef<HTMLElement | null>(null)
    const focusMenu = useCallback((element: HTMLDivElement | null): void => {
        if (element) {
            previousFocus.current = document.activeElement as HTMLElement | null
        }
        element?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true })
    }, [])

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (event.key === 'Escape' || event.key === 'Tab') {
            previousFocus.current?.focus({ preventScroll: true })
            close()
            return
        }
        if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
            return
        }
        event.preventDefault()
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'))
        const current = buttons.indexOf(document.activeElement as HTMLElement)
        const next =
            event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? buttons.length - 1
                  : (current + (event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 1) + buttons.length) %
                    buttons.length
        buttons[next]?.focus({ preventScroll: true })
    }

    return (
        <Popover
            visible
            onClickOutside={close}
            padded={false}
            delayMs={0}
            className="BIDrilldownMenu"
            style={{
                position: 'fixed',
                left: Math.max(8, Math.min((interaction?.x ?? window.innerWidth / 2) - 150, window.innerWidth - 308)),
                top: Math.max(8, Math.min((interaction?.y ?? window.innerHeight / 2) - 210, window.innerHeight - 368)),
            }}
            overlay={
                <div
                    data-attr="bi-result-menu"
                    data-quill={todayRailNav ? '' : undefined}
                    onClickCapture={(event) => {
                        if (
                            interaction?.timestamp !== undefined &&
                            event.detail > 0 &&
                            !event.metaKey &&
                            !event.ctrlKey &&
                            !event.shiftKey &&
                            !event.altKey &&
                            event.timeStamp - interaction.timestamp >= 0 &&
                            event.timeStamp - interaction.timestamp <= 500 &&
                            Math.hypot(event.clientX - interaction.x, event.clientY - interaction.y) <= 6
                        ) {
                            event.preventDefault()
                            event.stopPropagation()
                            const filter = canFilter
                                ? actions.find((action) => action.className === 'BIDrilldownMenu__filter')
                                : undefined
                            filter ? filter.onClick() : close()
                        }
                    }}
                >
                    <div
                        className="BIDrilldownMenu__selection"
                        title={typeof selectedResult === 'string' ? selectedResult : undefined}
                    >
                        <span className="text-xs text-secondary truncate">
                            <span>{caption}</span>
                            <span>{canFilter ? ' · Click again to filter' : ' · Click again to close'}</span>
                        </span>
                        <strong className="truncate">{selectedResult}</strong>
                    </div>
                    <div
                        className="BIDrilldownMenu__wheel"
                        role="menu"
                        aria-label={
                            typeof selectedResult === 'string' ? `Explore ${selectedResult}` : 'Explore this result'
                        }
                        onKeyDown={onKeyDown}
                        ref={focusMenu}
                    >
                        {actions.map(({ name, icon, className, onClick, disabledReason, to, inPlace }) => {
                            const content = (
                                <span className="BIDrilldownMenu__action-label">
                                    {icon}
                                    <span>{name}</span>
                                </span>
                            )
                            const sharedProps = {
                                className,
                                onClick: (event: MouseEvent<HTMLElement>): void => {
                                    if (
                                        event.button !== 0 ||
                                        event.metaKey ||
                                        event.ctrlKey ||
                                        event.shiftKey ||
                                        event.altKey
                                    ) {
                                        return
                                    }
                                    if (inPlace) {
                                        event.preventDefault()
                                    }
                                    onClick()
                                },
                                disabledReason,
                                role: 'menuitem',
                                'aria-label': name,
                            }
                            return todayRailNav ? (
                                <Button
                                    key={name}
                                    {...sharedProps}
                                    variant="default"
                                    render={to && !disabledReason ? <LinkPrimitive to={to} /> : undefined}
                                >
                                    {content}
                                </Button>
                            ) : (
                                <LemonButton key={name} {...sharedProps} to={to} type="tertiary">
                                    {content}
                                </LemonButton>
                            )
                        })}
                        {!canFilter && (
                            <button
                                type="button"
                                className="BIDrilldownMenu__empty-center"
                                aria-label="Close result menu"
                                onClick={close}
                            />
                        )}
                        <svg className="BIDrilldownMenu__dividers" viewBox="0 0 300 300" aria-hidden="true">
                            <path d="M20 75 L103 123 M197 123 L280 75 M150 204 L150 300" />
                        </svg>
                    </div>
                </div>
            }
        />
    )
}
