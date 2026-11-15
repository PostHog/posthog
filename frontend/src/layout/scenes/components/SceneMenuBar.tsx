import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Children, ComponentProps, ReactNode, useContext, useEffect } from 'react'
import { createPortal } from 'react-dom'

import { IconExternal, IconGear, IconSidePanel, IconSparkles } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenuCheckboxItem,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Menubar,
    MenubarCheckboxItem,
    MenubarContent,
    MenubarItem,
    MenubarMenu,
    MenubarRadioGroup,
    MenubarRadioItem,
    MenubarSeparator,
    MenubarShortcut,
    MenubarSub,
    MenubarSubContent,
    MenubarSubTrigger,
    MenubarTrigger,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { SetupReminderContext } from 'lib/components/ProductEmptyState/setupReminderContext'
import { IconBlank } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { SidePanelTab } from '~/types'

import { captureSceneMenuBar } from './captureSceneMenuBar'
import { SceneContentContext } from './SceneContent'
import { SceneFlatMenu } from './SceneFlatMenu'
import { SceneFlatMenuGroup } from './SceneFlatMenuGroup'
import { SceneMenuBarRenderContext } from './sceneMenuBarRenderContext'
import { useFillSceneMenuBarSlot, useSceneMenuBarSlot } from './SceneMenuBarSlotProvider'
import { getSceneSettingsUrl } from './sceneSettingsUrl'

/**
 * Scene layouts where the surrounding container applies horizontal/vertical padding to
 * scene content. In those layouts the menu bar uses negative margins to span edge-to-edge.
 * For unpadded layouts (app-raw, plain, etc.) the negatives would overshoot — we skip them.
 */
const PADDED_LAYOUTS = new Set(['app', 'app-container', 'app-full-scene-height'])

type SceneMenuBarProps = {
    children?: ReactNode
    className?: string
}

export function SceneMenuBar({ children, className }: SceneMenuBarProps): JSX.Element {
    const { sceneLayoutConfig } = useValues(sceneLayoutLogic)
    const layout = sceneLayoutConfig?.layout ?? 'app'
    const isPaddedLayout = PADDED_LAYOUTS.has(layout)
    const { todayRailEnabled } = useValues(todayShellLogic)
    const titleSlot = useSceneMenuBarSlot()
    // Under the Today layout the menus sit in the title row after the scene name. A scene without a title keeps the bar.
    const slot = todayRailEnabled ? titleSlot : null
    useFillSceneMenuBarSlot(!!slot)

    // A skipped product empty state parks its "isn't receiving data yet" reminder here so it
    // sits just below the bar. Null for every other scene, so nothing extra renders.
    const setupReminder = useContext(SetupReminderContext)

    useEffect(() => {
        captureSceneMenuBar('scene menu bar shown')
    }, [])

    if (slot) {
        return (
            <>
                {createPortal(
                    <SceneFlatMenu>
                        {children}
                        <SceneMenuBarHelpMenu />
                    </SceneFlatMenu>,
                    slot
                )}
                {setupReminder}
            </>
        )
    }

    const bar = (
        <div
            data-attr="scene-menu-bar"
            data-scene-layout={layout}
            className={cn(
                'scene-menu-bar flex items-center px-0.5 py-0.5 border-b border-primary justify-between',
                // Below `lg` the navigation toggle floats over the top-left corner of the scene.
                'max-lg:pl-10',
                // Bleed past the scene container's padding so the bar feels full-width — only
                // safe when the layout actually has padding to cancel. Unpadded layouts
                // (app-raw, plain, etc.) would overflow.
                isPaddedLayout && '-mx-4 -mt-4',
                // When LemonTabs is the immediately preceding sibling it already bleeds with
                // its own -mt-6, leaving the menu bar floating in the flex `gap-y-*`. Pull the
                // bar up so they sit flush.
                '[.LemonTabs+&]:-mt-6',
                className
            )}
        >
            {/*
                  Right-side cluster lives OUTSIDE <Menubar> so it doesn't pollute the Menubar's
                  CompositeRoot — that's what coordinates ArrowLeft/Right navigation and
                  hover-to-switch between menus.
                */}
            <Menubar className="gap-0 border-0">
                {children}
                {todayRailEnabled && <SceneMenuBarHelpMenu />}
            </Menubar>

            <Badge className={cn('hidden @[800px]:flex', todayRailEnabled && 'me-1')}>OS-like menu (alpha)</Badge>
            {!todayRailEnabled && <SceneMenuBarRightLinks />}
        </div>
    )

    return (
        <>
            {bar}
            {setupReminder}
        </>
    )
}

/** The last menu, as in macOS. Every scene gets it, so scenes never add their own. */
export function SceneMenuBarHelpMenu(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { productKey } = useContext(SceneContentContext)
    const settingsUrl = getSceneSettingsUrl(productKey)

    return (
        <SceneMenuBarMenu label="Help" dataAttr="scene-menu-bar-help">
            {settingsUrl && (
                <>
                    <SceneMenuBarItem
                        data-attr="scene-menu-bar-settings"
                        onClick={() => router.actions.push(settingsUrl)}
                    >
                        <IconGear />
                        Settings
                    </SceneMenuBarItem>
                    <SceneMenuBarSeparator />
                </>
            )}
            <SceneMenuBarItem
                data-attr="scene-menu-bar-docs"
                onClick={() => window.open('https://posthog.com/docs', '_blank', 'noopener')}
            >
                <IconExternal />
                Docs
            </SceneMenuBarItem>
            <SceneMenuBarItem
                data-attr="scene-menu-bar-support"
                opensFloatingUi
                onClick={() => openSidePanel(SidePanelTab.Support)}
            >
                <IconSidePanel />
                Support
            </SceneMenuBarItem>
        </SceneMenuBarMenu>
    )
}

const RIGHT_TRIGGER_CLASSES = 'px-2 h-7 rounded-sm text-xs font-medium inline-flex items-center gap-1 text-foreground'
// The right links drop to icons in a narrow scene so the bar never pushes the scene sideways.
const RIGHT_TRIGGER_LABEL_CLASSES = 'hidden @min-[36rem]/main-content:inline'

function SceneMenuBarRightLinks(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { productKey } = useContext(SceneContentContext)
    const settingsUrl = getSceneSettingsUrl(productKey)

    return (
        <div className="flex items-center gap-px pr-1">
            {settingsUrl && (
                <Button
                    data-attr="scene-menu-bar-settings"
                    aria-label="Settings"
                    className={RIGHT_TRIGGER_CLASSES}
                    onClick={() => captureSceneMenuBar('scene menu bar right link clicked', { link: 'settings' })}
                    render={<LinkPrimitive to={settingsUrl} />}
                >
                    <span className={RIGHT_TRIGGER_LABEL_CLASSES}>Settings</span>
                    <IconGear />
                </Button>
            )}
            <Button
                data-attr="scene-menu-bar-docs"
                aria-label="Docs"
                className={RIGHT_TRIGGER_CLASSES}
                onClick={() => captureSceneMenuBar('scene menu bar right link clicked', { link: 'docs' })}
                render={<LinkPrimitive to="https://posthog.com/docs" target="_blank" />}
            >
                <span className={RIGHT_TRIGGER_LABEL_CLASSES}>Docs</span>
                <IconExternal />
            </Button>
            <Button
                type="button"
                onClick={() => {
                    captureSceneMenuBar('scene menu bar right link clicked', { link: 'support' })
                    openSidePanel(SidePanelTab.Support)
                }}
                data-attr="scene-menu-bar-support"
                aria-label="Support"
                className={RIGHT_TRIGGER_CLASSES}
            >
                <span className={RIGHT_TRIGGER_LABEL_CLASSES}>Support</span>
                <IconSidePanel />
            </Button>
            <Button
                type="button"
                onClick={() => {
                    captureSceneMenuBar('scene menu bar right link clicked', { link: 'ai' })
                    openSidePanel(SidePanelTab.Max)
                }}
                data-attr="scene-menu-bar-ai"
                aria-label="PostHog AI"
                className={RIGHT_TRIGGER_CLASSES}
                variant="outline"
            >
                <IconSparkles className="text-ai group-hover/button-primitive:animate-hue-rotate" />
                <span className={RIGHT_TRIGGER_LABEL_CLASSES}>PostHog AI</span>
            </Button>
        </div>
    )
}

/**
 * Canonical menu set for SceneMenuBar. Use these labels in this order so the bar feels
 * consistent across PostHog scenes. Render only the menus your scene actually needs.
 *
 * Order: File → Edit → View → Metadata → Staff only (→ Help, added by the bar itself under the Today layout)
 *
 * - **File** — `<SceneMenuBarSubMenu label="Create">` at the top, then file/project ops,
 *   Export sub-menu, ──, **Delete / Archive / Restore** (destructive, at the bottom).
 * - **Edit** — Duplicate, Rename, scene-specific edits, state mutations
 *   (Pause/Resume, Activate/Deactivate), ──, grouped toggles
 *   (Pin/Fullscreen/Favorite/etc) using `<SceneMenuBarCheckboxItem>`.
 * - **View** *(conditional)* — Cross-resource viewing actions: View recordings,
 *   View metalytics, View related X. Anything that navigates the user to *see* something
 *   tangentially related to the current resource. Skip when there's nothing to view.
 * - **Metadata** *(use `SceneMenuBarPopover`)* — Tags, Evaluation contexts, Stage,
 *   Activity indicator, ExternalReferences.
 * - **Staff only** *(conditional)* — Debug panels, internal toggles.
 *
 * Right cluster includes PostHog AI, Docs, Support, and Settings when configured for the scene's product. Under the
 * Today layout Docs, Support and Settings move to the Help menu.
 *
 * Full conventions: `.agents/skills/scene-menu-bar/SKILL.md`.
 */
export type SceneMenuBarLabel = 'File' | 'Edit' | 'View' | 'Metadata' | 'Staff only' | (string & {})

function flatSectionLabel(label: SceneMenuBarLabel): string | undefined {
    return label === 'File' ? undefined : label
}

const FLAT_ROW_ICON_SPACER = <span aria-hidden className="size-3.5 shrink-0" />

type SceneMenuBarMenuProps = {
    /** Top-level menu label. Use canonical labels (File / Edit / View / Metadata / Staff only). */
    label: SceneMenuBarLabel
    children: ReactNode
    /** data-attr applied to the trigger for tests. In the flat menu it goes on the section. */
    dataAttr?: string
    /** Optional content alignment. The flat menu ignores it. */
    align?: 'start' | 'center' | 'end'
    /** Class applied to the dropdown content — useful for widening menus that hold rich widgets. The flat menu ignores it. */
    contentClassName?: string
    /**
     * Force the trigger into a disabled state regardless of children. Use when the menu's
     * items are guaranteed to be empty in a known state (e.g. unsaved resource) and you
     * still want the label visible. For purely empty children the trigger auto-disables.
     */
    disabled?: boolean
}

/**
 * True when no direct child of the menu would render anything visible. Catches
 * `{false && <Item/>}` / `{null}` / empty fragments. Components that return null at
 * render (e.g. SceneMenuBarFileItems with no tree entry) cannot be detected from the
 * parent — gate those at the caller or pass `disabled` explicitly.
 */
function hasNoRenderableChildren(children: ReactNode): boolean {
    return Children.toArray(children).length === 0
}

const MENU_TRIGGER_CLASSES =
    'flex items-center whitespace-nowrap outline-hidden select-none px-2 h-7 rounded-sm text-xs font-medium hover:bg-fill-hover data-[popup-open]:bg-fill-selected disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent'

export function SceneMenuBarMenu({
    label,
    children,
    dataAttr,
    align = 'start',
    contentClassName,
    disabled,
}: SceneMenuBarMenuProps): JSX.Element | null {
    const render = useContext(SceneMenuBarRenderContext)
    const isDisabled = disabled || hasNoRenderableChildren(children)
    if (render.kind === 'popover-host') {
        return null
    }
    if (render.kind === 'flat') {
        return isDisabled ? null : (
            <SceneFlatMenuGroup label={flatSectionLabel(label)} dataAttr={dataAttr}>
                {children}
            </SceneFlatMenuGroup>
        )
    }
    return (
        <MenubarMenu
            onOpenChange={(open: boolean) => {
                if (open) {
                    captureSceneMenuBar('scene menu bar menu opened', { menu: label })
                }
            }}
        >
            <MenubarTrigger data-attr={dataAttr} disabled={isDisabled} className={MENU_TRIGGER_CLASSES}>
                {label}
            </MenubarTrigger>
            <MenubarContent
                align={align}
                className={cn(
                    // Override DropdownMenuContent's default `w-(--anchor-width)` so menus size to content.
                    'w-auto min-w-max',
                    // Items that render nothing can leave a separator at an edge or two in a row. Hide those.
                    '[&_[role=separator]:is(:first-child,:last-child)]:hidden [&_[role=separator]+[role=separator]]:hidden',
                    contentClassName
                )}
            >
                {children}
            </MenubarContent>
        </MenubarMenu>
    )
}

type SceneMenuBarItemProps = ComponentProps<typeof MenubarItem> & {
    /**
     * Append a trailing ellipsis ("…") to the label — Mac-style affordance signalling that
     * the action opens additional floating UI (modal, popover, dialog, side panel).
     * Use for items like "Subscribe…", "Duplicate…", "Manage with Terraform…". Skip for
     * direct actions ("Delete feature flag") and same-page navigations.
     */
    opensFloatingUi?: boolean
    /**
     * Hover hint, typically the reason a disabled item can't be used. The menu bar applies it as the native title, the
     * flat menu as a tooltip beside the row.
     */
    tooltip?: string
}

/**
 * Pass `variant="destructive"` for any "Delete X" / "Archive X" / "Remove X" action so the
 * visual signal is consistent across PostHog scenes.
 */
export function SceneMenuBarItem({
    opensFloatingUi,
    tooltip,
    children,
    onClick,
    ...props
}: SceneMenuBarItemProps): JSX.Element | null {
    const render = useContext(SceneMenuBarRenderContext)
    const handleClick: NonNullable<SceneMenuBarItemProps['onClick']> = (e) => {
        const dataAttr = (props as Record<string, unknown>)['data-attr']
        captureSceneMenuBar('scene menu bar item clicked', {
            item: typeof dataAttr === 'string' ? dataAttr : typeof children === 'string' ? children : undefined,
            ...(render.kind === 'flat' ? render.getCaptureProperties() : {}),
        })
        onClick?.(e)
    }
    const ellipsis = opensFloatingUi && (
        // `-ms-2` cancels the item's flex `gap-2` so the ellipsis sits flush against the trailing edge of the label
        // instead of getting a full gap inserted.
        <span aria-hidden className="-ms-2">
            …
        </span>
    )

    if (render.kind === 'popover-host') {
        return null
    }
    if (render.kind === 'flat') {
        const item = (
            <DropdownMenuItem tooltip={tooltip} onClick={handleClick} {...props}>
                {children}
                {ellipsis}
            </DropdownMenuItem>
        )
        if (props.variant !== 'destructive' || !render.inList) {
            return item
        }
        // The footer is a DOM node inside the list, so the filter and arrow keys, which follow document order, reach
        // the item where it shows. Context survives the portal, so an AccessControlAction wrapper still applies.
        return render.destructiveFooter ? createPortal(item, render.destructiveFooter) : null
    }
    return (
        <MenubarItem title={tooltip} onClick={handleClick} {...props}>
            {children}
            {ellipsis}
        </MenubarItem>
    )
}

/**
 * Use for toggle-style items (e.g. "Show debug panel", "Pin", "Favorite"). Renders a
 * checkmark indicator that reflects `checked` state.
 */
export function SceneMenuBarCheckboxItem(props: ComponentProps<typeof MenubarCheckboxItem>): JSX.Element {
    const render = useContext(SceneMenuBarRenderContext)
    return render.kind === 'menubar' ? <MenubarCheckboxItem {...props} /> : <DropdownMenuCheckboxItem {...props} />
}

/**
 * Wrap multiple `SceneMenuBarRadioItem` instances to make them mutually-exclusive.
 * Bind via `value` + `onValueChange`.
 */
export function SceneMenuBarRadioGroup(props: ComponentProps<typeof MenubarRadioGroup>): JSX.Element {
    const render = useContext(SceneMenuBarRenderContext)
    return render.kind === 'menubar' ? <MenubarRadioGroup {...props} /> : <DropdownMenuRadioGroup {...props} />
}

/**
 * One of several mutually-exclusive options inside a `<SceneMenuBarRadioGroup>`.
 */
export function SceneMenuBarRadioItem(props: ComponentProps<typeof MenubarRadioItem>): JSX.Element {
    const render = useContext(SceneMenuBarRenderContext)
    return render.kind === 'menubar' ? <MenubarRadioItem {...props} /> : <DropdownMenuRadioItem {...props} />
}

export function SceneMenuBarSeparator(props: ComponentProps<typeof MenubarSeparator>): JSX.Element {
    const render = useContext(SceneMenuBarRenderContext)
    return render.kind === 'menubar' ? <MenubarSeparator {...props} /> : <DropdownMenuSeparator {...props} />
}

export function SceneMenuBarShortcut(props: ComponentProps<typeof MenubarShortcut>): JSX.Element {
    const render = useContext(SceneMenuBarRenderContext)
    return render.kind === 'menubar' ? <MenubarShortcut {...props} /> : <DropdownMenuShortcut {...props} />
}

type SceneMenuBarSubMenuProps = {
    label: ReactNode
    children: ReactNode
    /**
     * Whether to prepend a blank icon slot to the trigger so the label aligns with sibling
     * items that have leading icons. Default true — opt out via `withIconBlank={false}`
     * when the trigger already supplies its own leading icon.
     */
    withIconBlank?: boolean
    /**
     * In the flat menu of the Today layout, a submenu renders by default as a group of rows under its label, in place,
     * so the search finds its rows. The search only reaches one menu level. Pass `keepAsSubmenu` to render a real
     * submenu instead, for a long list of toggles (such as visible tiles) or a submenu that holds another submenu.
     * Its rows then stay out of the search and the destructive group, and submenus inside it stay submenus.
     * The legacy menu bar always renders a submenu and ignores this prop.
     */
    keepAsSubmenu?: boolean
}

export function SceneMenuBarSubMenu({
    label,
    children,
    withIconBlank = true,
    keepAsSubmenu = false,
}: SceneMenuBarSubMenuProps): JSX.Element | null {
    const render = useContext(SceneMenuBarRenderContext)
    if (render.kind === 'popover-host') {
        return null
    }
    if (render.kind === 'flat') {
        if (render.inList && !keepAsSubmenu) {
            return <SceneFlatMenuGroup label={label}>{children}</SceneFlatMenuGroup>
        }
        return (
            <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                    {withIconBlank && FLAT_ROW_ICON_SPACER}
                    {label}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                    <SceneMenuBarRenderContext.Provider value={{ ...render, inList: false }}>
                        {children}
                    </SceneMenuBarRenderContext.Provider>
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        )
    }
    return (
        <MenubarSub>
            <MenubarSubTrigger>
                {withIconBlank && <IconBlank />}
                {label}
            </MenubarSubTrigger>
            <MenubarSubContent>{children}</MenubarSubContent>
        </MenubarSub>
    )
}

type SceneMenuBarPopoverProps = {
    /** Trigger label — styled identically to a SceneMenuBarMenu trigger */
    label: SceneMenuBarLabel
    children: ReactNode
    dataAttr?: string
    align?: 'start' | 'center' | 'end'
    contentClassName?: string
}

/**
 * Drop-in alternative to `SceneMenuBarMenu` for menus whose content needs rich form controls
 * (text inputs, comboboxes, etc). Renders a Popover instead of a Menu — Menu.Popup intercepts
 * keystrokes for typeahead/arrow-nav which prevents text inputs from receiving input.
 *
 * Use for: Metadata-style panels with `<TagsCombobox>`, inline edit fields, free-form widgets.
 * Avoid for: lists of action items (use `SceneMenuBarMenu` so keyboard nav still works).
 *
 * Trade-off: Popover trigger does NOT participate in the Menubar's CompositeRoot, so
 * ArrowLeft/Right won't switch to/from it.
 */
export function SceneMenuBarPopover({
    label,
    children,
    dataAttr,
    align = 'start',
    contentClassName,
}: SceneMenuBarPopoverProps): JSX.Element {
    const render = useContext(SceneMenuBarRenderContext)
    const popoverId = dataAttr ?? label

    if (render.kind === 'popover-host') {
        return (
            <Popover
                open={render.openPopoverId === popoverId}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        render.closePopover()
                    }
                }}
            >
                <PopoverContent
                    anchor={render.anchor}
                    finalFocus={render.anchor}
                    align={align}
                    className={cn('w-80 p-2', contentClassName)}
                >
                    {children}
                </PopoverContent>
            </Popover>
        )
    }
    if (render.kind === 'flat') {
        const { openPopover, getCaptureProperties } = render
        return (
            <SceneFlatMenuGroup>
                <DropdownMenuItem
                    data-attr={dataAttr}
                    onClick={() => {
                        captureSceneMenuBar('scene menu bar item clicked', {
                            item: dataAttr ?? label,
                            ...getCaptureProperties(),
                        })
                        openPopover(popoverId)
                    }}
                >
                    {FLAT_ROW_ICON_SPACER}
                    {label}
                    <span aria-hidden className="-ms-2">
                        …
                    </span>
                </DropdownMenuItem>
            </SceneFlatMenuGroup>
        )
    }
    return (
        <Popover>
            <PopoverTrigger data-attr={dataAttr} className={MENU_TRIGGER_CLASSES}>
                {label}
            </PopoverTrigger>
            <PopoverContent align={align} className={cn('w-80 p-2', contentClassName)}>
                {children}
            </PopoverContent>
        </Popover>
    )
}
