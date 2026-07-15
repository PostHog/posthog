import { useEffect, useRef, useState } from 'react'

import { IconCopy, IconExternal, IconPlus } from '@posthog/icons'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { isDesktopApp } from 'lib/utils/isDesktopApp'
import { newInternalTab } from 'lib/utils/newInternalTab'

interface LinkMenuTarget {
    x: number
    y: number
    /** Absolute URL of the link */
    url: string
    /** pathname + search + hash when the link points at the app's own origin, otherwise null */
    internalPath: string | null
    text: string
}

/**
 * Desktop-app-only (products/desktop): a right-click menu for every link that doesn't already
 * have one. A single document-level listener catches `contextmenu` on any `<a href>`; components
 * that provide their own context menu (e.g. Radix ContextMenu triggers, like the scene tabs or
 * the project tree) have already called `preventDefault` by the time the event bubbles here, so
 * they keep their menus. Mounted once from App when `isDesktopApp()`.
 */
export function DesktopLinkContextMenu(): JSX.Element | null {
    const [target, setTarget] = useState<LinkMenuTarget | null>(null)
    const triggerRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (!isDesktopApp()) {
            return
        }
        const onContextMenu = (event: MouseEvent): void => {
            if (event.defaultPrevented) {
                return
            }
            const anchor = (event.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
            if (!anchor) {
                return
            }
            const rawHref = anchor.getAttribute('href')
            if (!rawHref || rawHref === '#') {
                return
            }
            let url: URL
            try {
                // anchor.href is the browser-resolved absolute URL
                url = new URL(anchor.href)
            } catch {
                return
            }
            if (url.protocol === 'javascript:') {
                return
            }
            event.preventDefault()
            setTarget({
                x: event.clientX,
                y: event.clientY,
                url: url.toString(),
                internalPath: url.origin === window.location.origin ? `${url.pathname}${url.search}${url.hash}` : null,
                text: (anchor.textContent ?? '').trim(),
            })
        }
        document.addEventListener('contextmenu', onContextMenu)
        return () => document.removeEventListener('contextmenu', onContextMenu)
    }, [])

    useEffect(() => {
        if (target && triggerRef.current) {
            // Radix opens the menu at the pointer coordinates of the contextmenu event, so
            // re-dispatch one on our proxy trigger at the original click position
            triggerRef.current.dispatchEvent(
                new MouseEvent('contextmenu', {
                    bubbles: true,
                    cancelable: true,
                    clientX: target.x,
                    clientY: target.y,
                })
            )
        }
    }, [target])

    if (!target) {
        return null
    }

    const copyToClipboard = (value: string, what: string): void => {
        navigator.clipboard
            .writeText(value)
            .then(() => lemonToast.success(`${what} copied to clipboard`))
            .catch(() => lemonToast.error(`Failed to copy ${what.toLowerCase()} to clipboard`))
    }

    const openExternally = (): void => {
        // The desktop main process routes non-local origins to the system browser,
        // and local-origin URLs to a new PostHog window
        window.open(target.url, '_blank', 'noopener,noreferrer')
    }

    return (
        <ContextMenu
            onOpenChange={(open) => {
                if (!open) {
                    setTarget(null)
                }
            }}
        >
            <ContextMenuTrigger asChild>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div ref={triggerRef} className="fixed size-0" style={{ left: target.x, top: target.y }} />
            </ContextMenuTrigger>
            <ContextMenuContent className="max-w-[300px]">
                <ContextMenuGroup>
                    {target.internalPath ? (
                        <>
                            <ContextMenuItem asChild>
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() =>
                                        newInternalTab(target.internalPath ?? undefined, {
                                            activate: true,
                                            title: target.text || undefined,
                                        })
                                    }
                                >
                                    <IconPlus /> Open in new tab
                                </ButtonPrimitive>
                            </ContextMenuItem>
                            <ContextMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={openExternally}>
                                    <IconExternal /> Open in new window
                                </ButtonPrimitive>
                            </ContextMenuItem>
                        </>
                    ) : (
                        <ContextMenuItem asChild>
                            <ButtonPrimitive menuItem onClick={openExternally}>
                                <IconExternal />{' '}
                                {target.url.startsWith('mailto:') ? 'Open in email app' : 'Open in browser'}
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    )}
                    <ContextMenuSeparator />
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => copyToClipboard(target.url, 'URL')}>
                            <IconCopy /> Copy URL
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    {target.text ? (
                        <ContextMenuItem asChild>
                            <ButtonPrimitive menuItem onClick={() => copyToClipboard(target.text, 'Link text')}>
                                <IconCopy /> Copy link text
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    ) : null}
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}
