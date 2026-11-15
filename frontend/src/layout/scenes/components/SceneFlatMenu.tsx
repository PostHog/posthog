import { ReactNode, useMemo, useRef, useState } from 'react'

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
import { FlatRender, PopoverHostRender, SceneMenuBarRenderContext } from './sceneMenuBarRenderContext'
import { useCollapseFlatMenuRows } from './useCollapseFlatMenuRows'

const TRIGGER_LABEL = 'More actions'

type SceneFlatMenuProps = {
    children: ReactNode
    helpOnly?: boolean
}

export function SceneFlatMenu({ children, helpOnly = false }: SceneFlatMenuProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [list, setList] = useState<HTMLDivElement | null>(null)
    const [destructiveFooter, setDestructiveFooter] = useState<HTMLDivElement | null>(null)
    const [openPopoverId, setOpenPopoverId] = useState<string | null>(null)
    const pendingPopoverIdRef = useRef<string | null>(null)
    const searchActiveRef = useRef(false)
    const searchCapturedRef = useRef(false)
    useCollapseFlatMenuRows(list)

    const flatRender = useMemo<FlatRender>(() => {
        const getCaptureProperties = (): Record<string, unknown> => ({
            layout: 'flat',
            search_active: searchActiveRef.current,
            ...(helpOnly ? { help_only: true } : {}),
        })
        return {
            kind: 'flat',
            inList: true,
            destructiveFooter,
            openPopover: (id) => {
                pendingPopoverIdRef.current = id
            },
            getCaptureProperties,
        }
    }, [destructiveFooter, helpOnly])

    const popoverHostRender = useMemo<PopoverHostRender>(
        () => ({
            kind: 'popover-host',
            openPopoverId,
            closePopover: () => setOpenPopoverId(null),
            anchor: triggerRef,
        }),
        [openPopoverId]
    )

    return (
        <div data-attr="scene-menu-bar" className="scene-menu-bar flex items-center">
            <SceneMenuBarRenderContext.Provider value={popoverHostRender}>
                {children}
            </SceneMenuBarRenderContext.Provider>
            <DropdownMenuFilterProvider
                autoHighlight
                onValueChange={(value: string) => {
                    searchActiveRef.current = value !== ''
                    if (value !== '' && !searchCapturedRef.current) {
                        searchCapturedRef.current = true
                        captureSceneMenuBar('scene menu bar searched', flatRender.getCaptureProperties())
                    }
                }}
            >
                <DropdownMenu
                    onOpenChange={(open: boolean) => {
                        if (open) {
                            searchCapturedRef.current = false
                            captureSceneMenuBar('scene menu bar menu opened', {
                                menu: null,
                                ...flatRender.getCaptureProperties(),
                            })
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
                    {/* quill caps a flush menu's scroller, the popup's only child, at 72 spacing units, which shows only a few
                        rows of a rich scene. Utilities outrank quill's components layer, so this cap replaces it: the list
                        grows with the room below the button, up to 70% of the viewport. */}
                    <DropdownMenuContent align="start" flush className="*:max-h-[min(70dvh,var(--available-height))]">
                        <DropdownMenuInput placeholder="Search actions" aria-label="Search actions" />
                        <DropdownMenuEmpty>No matching actions</DropdownMenuEmpty>
                        <DropdownMenuList ref={setList} className="[&_[data-scene-menu-collapsed]]:hidden">
                            <SceneMenuBarRenderContext.Provider value={flatRender}>
                                {children}
                            </SceneMenuBarRenderContext.Provider>
                            <DropdownMenuGroup data-attr="scene-menu-bar-destructive">
                                <DropdownMenuSeparator />
                                <div ref={setDestructiveFooter} className="contents" />
                            </DropdownMenuGroup>
                        </DropdownMenuList>
                    </DropdownMenuContent>
                </DropdownMenu>
            </DropdownMenuFilterProvider>
        </div>
    )
}
