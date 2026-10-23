import './ResultMenu.scss'

import { KeyboardEvent, MouseEvent, ReactNode, useCallback, useRef } from 'react'

import { Popover } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface ResultMenuAction {
    name: string
    icon: JSX.Element
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
    close,
}: {
    selectedResult: ReactNode
    caption: string
    interaction: { x: number; y: number; timestamp?: number } | null
    actions: ResultMenuAction[]
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
                left: Math.max(8, Math.min((interaction?.x ?? window.innerWidth / 2) + 8, window.innerWidth - 308)),
                top: Math.max(8, Math.min((interaction?.y ?? window.innerHeight / 2) + 8, window.innerHeight - 248)),
            }}
            overlay={
                <div data-attr="bi-result-menu" data-quill={todayRailNav ? '' : undefined}>
                    <div
                        className="BIDrilldownMenu__selection"
                        title={typeof selectedResult === 'string' ? selectedResult : undefined}
                    >
                        <span className="text-xs text-secondary truncate">
                            <span>{caption}</span>
                        </span>
                        <strong className="truncate">{selectedResult}</strong>
                    </div>
                    <div
                        className="BIDrilldownMenu__items"
                        role="menu"
                        aria-label={
                            typeof selectedResult === 'string' ? `Explore ${selectedResult}` : 'Explore this result'
                        }
                        onKeyDown={onKeyDown}
                        ref={focusMenu}
                    >
                        {todayRailNav ? (
                            actions.map(({ name, icon, className, onClick, disabledReason, to, inPlace }) => {
                                const content = (
                                    <span className="BIDrilldownMenu__action-label">
                                        {icon}
                                        <span>{name}</span>
                                    </span>
                                )
                                const sharedProps = {
                                    className,
                                    onClick: (event: MouseEvent): void => {
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
                                return (
                                    <Button
                                        key={name}
                                        {...sharedProps}
                                        variant="default"
                                        left
                                        render={to && !disabledReason ? <LinkPrimitive to={to} /> : undefined}
                                    >
                                        {content}
                                    </Button>
                                )
                            })
                        ) : (
                            <LemonMenuOverlay
                                items={actions.map(
                                    ({
                                        name,
                                        icon,
                                        className,
                                        onClick,
                                        disabledReason,
                                        to,
                                        inPlace,
                                    }): LemonMenuItem => {
                                        const item = {
                                            label: name,
                                            icon,
                                            className,
                                            disabledReason,
                                            onClick: (event: MouseEvent): void => {
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
                                        }
                                        return to && !disabledReason ? { ...item, to } : item
                                    }
                                )}
                            />
                        )}
                    </div>
                </div>
            }
        />
    )
}
