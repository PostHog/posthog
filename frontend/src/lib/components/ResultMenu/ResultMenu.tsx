import './ResultMenu.scss'

import { KeyboardEvent, MouseEvent, ReactNode, RefObject, useCallback, useEffect, useRef } from 'react'

import { Popover } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenuItem, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_NULL_DISPLAY,
    BREAKDOWN_OTHER_STRING_LABEL,
    BREAKDOWN_OTHER_DISPLAY,
    formatBreakdownLabel,
} from 'scenes/insights/utils'

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
    triggerRef,
}: {
    selectedResult: ReactNode
    caption: string
    interaction: { x: number; y: number; timestamp?: number } | null
    actions: ResultMenuAction[]
    close: () => void
    triggerRef?: RefObject<HTMLDivElement>
}): JSX.Element {
    if (typeof selectedResult === 'string') {
        selectedResult = formatBreakdownLabel(
            selectedResult,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            false
        )
            .replaceAll(BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_NULL_DISPLAY)
            .replaceAll(BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_OTHER_DISPLAY)
    }
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const previousFocus = useRef<HTMLElement | null>(null)
    const focusMenu = useCallback((element: HTMLDivElement | null): void => {
        if (element) {
            previousFocus.current = document.activeElement as HTMLElement | null
        }
        element?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true })
    }, [])

    useEffect(() => {
        const onScroll = (event: Event): void => {
            if (!(event.target instanceof Element && event.target.closest('[data-attr="bi-result-menu"]'))) {
                close()
            }
        }
        window.addEventListener('scroll', onScroll, true)
        window.addEventListener('resize', close)
        return () => {
            window.removeEventListener('scroll', onScroll, true)
            window.removeEventListener('resize', close)
        }
    }, [close])

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
            additionalRefs={triggerRef ? [triggerRef] : []}
            onClickOutside={close}
            padded={false}
            delayMs={0}
            className="ResultMenu"
            style={{
                position: 'fixed',
                left: Math.max(8, Math.min((interaction?.x ?? window.innerWidth / 2) + 8, window.innerWidth - 308)),
                top: Math.max(8, Math.min((interaction?.y ?? window.innerHeight / 2) + 8, window.innerHeight - 248)),
            }}
            overlay={
                <div data-attr="bi-result-menu" data-quill={todayRailNav ? '' : undefined}>
                    <div
                        className="ResultMenu__selection"
                        title={typeof selectedResult === 'string' ? selectedResult : undefined}
                    >
                        <span className="text-xs text-secondary truncate">
                            <span>{caption}</span>
                        </span>
                        <strong className="truncate">{selectedResult}</strong>
                    </div>
                    <div
                        className="ResultMenu__items"
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
                                    <span className="ResultMenu__action-label">
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
