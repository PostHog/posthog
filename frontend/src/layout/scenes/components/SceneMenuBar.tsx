import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { Children, ComponentProps, MouseEvent, ReactNode, useEffect } from 'react'

import { IconExternal, IconSidePanel, IconSparkles } from '@posthog/icons'
import {
    Badge,
    Button,
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

import { IconBlank } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'

import { sidePanelStateLogic } from '~/layout/navigation/sidepanel/sidePanelStateLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { SidePanelTab } from '~/types'

/**
 * Central instrumentation for the SceneMenuBar experiment (`SCENE_MENU_BAR` flag). Capturing
 * here means every scene that adopts the bar reports engagement without per-scene wiring.
 * Scene id is read off `sceneLogic` without subscribing so capture never triggers a re-render.
 */
function captureSceneMenuBar(event: string, properties: Record<string, unknown> = {}): void {
    posthog.capture(event, {
        scene: sceneLogic.findMounted()?.values.activeSceneId ?? null,
        ...properties,
    })
}

/**
 * Scene layouts where the surrounding container applies horizontal/vertical padding to
 * scene content. In those layouts the menu bar uses negative margins to span edge-to-edge.
 * For unpadded layouts (app-raw, plain, etc.) the negatives would overshoot — we skip them.
 */
const PADDED_LAYOUTS = new Set(['app', 'app-container', 'app-full-scene-height'])

type SceneMenuBarProps = {
    children: ReactNode
    className?: string
}

export function SceneMenuBar({ children, className }: SceneMenuBarProps): JSX.Element {
    const { sceneLayoutConfig } = useValues(sceneLayoutLogic)
    const layout = sceneLayoutConfig?.layout ?? 'app'
    const isPaddedLayout = PADDED_LAYOUTS.has(layout)

    useEffect(() => {
        captureSceneMenuBar('scene menu bar shown')
    }, [])

    return (
        <div
            data-attr="scene-menu-bar"
            data-scene-layout={layout}
            className={cn(
                'scene-menu-bar px-0.5 py-0.5 border-b border-primary flex items-center justify-between',
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
            <Menubar className="gap-0 border-0">{children}</Menubar>

            <Badge className="hidden @[800px]:flex">OS-like menu (alpha)</Badge>
            <SceneMenuBarRightLinks />
        </div>
    )
}

const RIGHT_TRIGGER_CLASSES = 'px-2 h-7 rounded-sm text-xs font-medium inline-flex items-center gap-1 text-foreground'

function SceneMenuBarRightLinks(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    return (
        <div className="flex items-center gap-px pr-1">
            <Button
                data-attr="scene-menu-bar-docs"
                className={RIGHT_TRIGGER_CLASSES}
                onClick={() => captureSceneMenuBar('scene menu bar right link clicked', { link: 'docs' })}
                render={<LinkPrimitive to="https://posthog.com/docs" target="_blank" />}
            >
                Docs
                <IconExternal />
            </Button>
            <Button
                type="button"
                onClick={() => {
                    captureSceneMenuBar('scene menu bar right link clicked', { link: 'support' })
                    openSidePanel(SidePanelTab.Support)
                }}
                data-attr="scene-menu-bar-support"
                className={RIGHT_TRIGGER_CLASSES}
            >
                Support
                <IconSidePanel />
            </Button>
            <Button
                type="button"
                onClick={() => {
                    captureSceneMenuBar('scene menu bar right link clicked', { link: 'ai' })
                    openSidePanel(SidePanelTab.Max)
                }}
                data-attr="scene-menu-bar-ai"
                className={RIGHT_TRIGGER_CLASSES}
                variant="outline"
            >
                <IconSparkles className="text-ai group-hover/button-primitive:animate-hue-rotate" />
                PostHog AI
            </Button>
        </div>
    )
}

/**
 * Canonical menu set for SceneMenuBar. Use these labels in this order so the bar feels
 * consistent across PostHog scenes. Render only the menus your scene actually needs.
 *
 * Order: File → Edit → View → Metadata → Staff only
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
 * Right cluster is universal: PostHog AI / Docs / Support.
 *
 * Full conventions: `.agents/skills/scene-menu-bar/SKILL.md`.
 */
export type SceneMenuBarLabel = 'File' | 'Edit' | 'View' | 'Metadata' | 'Staff only' | (string & {})

type SceneMenuBarMenuProps = {
    /** Top-level menu label. Use canonical labels (File / Edit / View / Metadata / Staff only). */
    label: SceneMenuBarLabel
    children: ReactNode
    /** data-attr applied to the trigger for tests */
    dataAttr?: string
    /** Optional content alignment */
    align?: 'start' | 'center' | 'end'
    /** Class applied to the dropdown content — useful for widening menus that hold rich widgets */
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

export function SceneMenuBarMenu({
    label,
    children,
    dataAttr,
    align = 'start',
    contentClassName,
    disabled,
}: SceneMenuBarMenuProps): JSX.Element {
    const isDisabled = disabled || hasNoRenderableChildren(children)
    return (
        <MenubarMenu
            onOpenChange={(open: boolean) => {
                if (open) {
                    captureSceneMenuBar('scene menu bar menu opened', { menu: label })
                }
            }}
        >
            <MenubarTrigger
                data-attr={dataAttr}
                disabled={isDisabled}
                className="px-2 h-7 rounded-sm text-xs font-medium hover:bg-fill-hover data-[popup-open]:bg-fill-selected disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
            >
                {label}
            </MenubarTrigger>
            <MenubarContent
                align={align}
                className={cn(
                    // Override DropdownMenuContent's default `w-(--anchor-width)` so menus size to content.
                    'w-auto min-w-max',
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
    /** Hover hint, typically the reason a disabled item can't be used. Applied as the native title. */
    tooltip?: string
}

/**
 * Pass `variant="destructive"` for any "Delete X" / "Archive X" / "Remove X" action so the
 * visual signal (red text + icon) is consistent across PostHog scenes.
 */
export function SceneMenuBarItem({
    opensFloatingUi,
    tooltip,
    children,
    onClick,
    ...props
}: SceneMenuBarItemProps): JSX.Element {
    const handleClick = (e: MouseEvent<HTMLDivElement>): void => {
        const dataAttr = (props as Record<string, unknown>)['data-attr']
        captureSceneMenuBar('scene menu bar item clicked', {
            item: typeof dataAttr === 'string' ? dataAttr : typeof children === 'string' ? children : undefined,
        })
        onClick?.(e)
    }
    return (
        <MenubarItem title={tooltip} onClick={handleClick} {...props}>
            {children}
            {/*
              `-ms-2` cancels MenubarItem's parent flex `gap-2` so the ellipsis sits flush
              against the trailing edge of the label instead of getting a full gap inserted.
            */}
            {opensFloatingUi && (
                <span aria-hidden className="-ms-2">
                    …
                </span>
            )}
        </MenubarItem>
    )
}

/**
 * Use for toggle-style items (e.g. "Show debug panel", "Pin", "Favorite"). Renders a
 * checkmark indicator that reflects `checked` state.
 */
export function SceneMenuBarCheckboxItem(props: ComponentProps<typeof MenubarCheckboxItem>): JSX.Element {
    return <MenubarCheckboxItem {...props} />
}

/**
 * Wrap multiple `SceneMenuBarRadioItem` instances to make them mutually-exclusive.
 * Bind via `value` + `onValueChange`.
 */
export function SceneMenuBarRadioGroup(props: ComponentProps<typeof MenubarRadioGroup>): JSX.Element {
    return <MenubarRadioGroup {...props} />
}

/**
 * One of several mutually-exclusive options inside a `<SceneMenuBarRadioGroup>`.
 */
export function SceneMenuBarRadioItem(props: ComponentProps<typeof MenubarRadioItem>): JSX.Element {
    return <MenubarRadioItem {...props} />
}

export function SceneMenuBarSeparator(props: ComponentProps<typeof MenubarSeparator>): JSX.Element {
    return <MenubarSeparator {...props} />
}

export function SceneMenuBarShortcut(props: ComponentProps<typeof MenubarShortcut>): JSX.Element {
    return <MenubarShortcut {...props} />
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
}

export function SceneMenuBarSubMenu({ label, children, withIconBlank = true }: SceneMenuBarSubMenuProps): JSX.Element {
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
    return (
        <Popover>
            <PopoverTrigger data-attr={dataAttr} render={<Button />}>
                {label}
            </PopoverTrigger>
            <PopoverContent align={align} className={cn('w-80 p-2', contentClassName)}>
                {children}
            </PopoverContent>
        </Popover>
    )
}
