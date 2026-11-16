import { ReactNode, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuEmpty,
    DropdownMenuFilterProvider,
    DropdownMenuGroup,
    DropdownMenuInput,
    DropdownMenuList,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { captureSceneMenuBar } from './captureSceneMenuBar'
import {
    ActionsMenuRender,
    MENU_PROBE_ATTRIBUTE,
    PopoverHostRender,
    ROW_PROBE_ATTRIBUTE,
    SceneMenuBarRenderContext,
} from './sceneMenuBarRenderContext'
import { COLLAPSED_ROWS_HIDDEN_CLASS, useCollapseMenuRows } from './useCollapseMenuRows'

const TRIGGER_LABEL = 'More actions'

function nonEmptyMenuLabels(host: HTMLElement): string[] {
    return Array.from(host.querySelectorAll(`[${MENU_PROBE_ATTRIBUTE}]`))
        .filter((menu) => menu.querySelector(`[${ROW_PROBE_ATTRIBUTE}]`))
        .map((menu) => menu.getAttribute(MENU_PROBE_ATTRIBUTE) ?? '')
}

function useNonEmptyMenus(host: HTMLElement | null): ReadonlySet<string> {
    const [labels, setLabels] = useState<string[]>([])
    useLayoutEffect(() => {
        if (!host) {
            return
        }
        const update = (): void => {
            const next = nonEmptyMenuLabels(host)
            setLabels((current) => (current.join('\n') === next.join('\n') ? current : next))
        }
        update()
        const observer = new MutationObserver(update)
        observer.observe(host, { childList: true, subtree: true })
        return () => observer.disconnect()
    }, [host])
    return useMemo(() => new Set(labels), [labels])
}

type SceneActionsMenuProps = {
    children: ReactNode
    helpOnly?: boolean
}

export function SceneActionsMenu({ children, helpOnly = false }: SceneActionsMenuProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [list, setList] = useState<HTMLDivElement | null>(null)
    const [host, setHost] = useState<HTMLDivElement | null>(null)
    const [query, setQuery] = useState('')
    const [openPopoverId, setOpenPopoverId] = useState<string | null>(null)
    const pendingPopoverIdRef = useRef<string | null>(null)
    const queryRef = useRef('')
    const searchCapturedRef = useRef(false)
    useCollapseMenuRows(list)
    const nonEmptyMenus = useNonEmptyMenus(host)
    const results = query !== ''

    const render = useMemo<ActionsMenuRender>(
        () => ({
            kind: 'actions-menu',
            level: helpOnly ? 'submenu' : 'top',
            results,
            destructiveOnly: false,
            path: [],
            nonEmptyMenus,
            openPopover: (id) => {
                pendingPopoverIdRef.current = id
            },
            getCaptureProperties: () => ({
                // pinned: analytics property value that tells this layout apart in the data
                layout: 'submenus',
                search_active: queryRef.current !== '',
                ...(helpOnly ? { help_only: true } : {}),
            }),
        }),
        [helpOnly, results, nonEmptyMenus]
    )
    const destructiveRender = useMemo<ActionsMenuRender>(() => ({ ...render, destructiveOnly: true }), [render])

    const popoverHostRender = useMemo<PopoverHostRender>(
        () => ({
            kind: 'popover-host',
            openPopoverId,
            closePopover: () => setOpenPopoverId(null),
            anchor: triggerRef,
        }),
        [openPopoverId]
    )

    const changeQuery = (value: string): void => {
        queryRef.current = value
        setQuery(value)
        if (value !== '' && !searchCapturedRef.current) {
            searchCapturedRef.current = true
            captureSceneMenuBar('scene menu bar searched', render.getCaptureProperties())
        }
    }

    const menu = (
        <DropdownMenu
            onOpenChange={(open, details) => {
                if (!open && details.reason === 'escape-key' && queryRef.current !== '') {
                    details.cancel()
                    changeQuery('')
                    return
                }
                if (open) {
                    searchCapturedRef.current = false
                    captureSceneMenuBar('scene menu bar menu opened', { menu: null, ...render.getCaptureProperties() })
                }
            }}
            onOpenChangeComplete={(open: boolean) => {
                // A popover row opens its popover only once the menu has closed and handed focus back to the
                // button, so the menu's focus return and outside-press handling never reach the popover.
                const pendingPopoverId = pendingPopoverIdRef.current
                if (!open && pendingPopoverId) {
                    pendingPopoverIdRef.current = null
                    setOpenPopoverId(pendingPopoverId)
                }
            }}
        >
            <DropdownMenuTrigger
                ref={triggerRef}
                data-attr="scene-menu-bar-trigger"
                render={<Button size="icon" aria-label={TRIGGER_LABEL} tooltip={TRIGGER_LABEL} />}
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            {helpOnly ? (
                <DropdownMenuContent align="start">
                    <SceneMenuBarRenderContext.Provider value={render}>{children}</SceneMenuBarRenderContext.Provider>
                </DropdownMenuContent>
            ) : (
                // quill caps a flush menu's scroller, the popup's only child, at 72 spacing units, which shows only a
                // few rows of a long result list. Utilities outrank quill's components layer, so this cap replaces
                // it: the list grows with the room below the button, up to 70% of the viewport.
                <DropdownMenuContent align="start" flush className="*:max-h-[min(70dvh,var(--available-height))]">
                    <DropdownMenuInput placeholder="Search actions" aria-label="Search actions" />
                    <DropdownMenuEmpty>No matching actions</DropdownMenuEmpty>
                    <DropdownMenuList ref={setList} className={COLLAPSED_ROWS_HIDDEN_CLASS}>
                        <SceneMenuBarRenderContext.Provider value={render}>
                            {children}
                        </SceneMenuBarRenderContext.Provider>
                        <DropdownMenuGroup data-attr="scene-menu-bar-destructive">
                            <DropdownMenuSeparator />
                            <SceneMenuBarRenderContext.Provider value={destructiveRender}>
                                {children}
                            </SceneMenuBarRenderContext.Provider>
                        </DropdownMenuGroup>
                    </DropdownMenuList>
                </DropdownMenuContent>
            )}
        </DropdownMenu>
    )

    return (
        <div data-attr="scene-menu-bar" className="scene-menu-bar flex items-center">
            <div ref={setHost} hidden>
                <SceneMenuBarRenderContext.Provider value={popoverHostRender}>
                    {children}
                </SceneMenuBarRenderContext.Provider>
            </div>
            {helpOnly ? (
                menu
            ) : (
                <DropdownMenuFilterProvider autoHighlight value={query} onValueChange={changeQuery}>
                    {menu}
                </DropdownMenuFilterProvider>
            )}
        </div>
    )
}
