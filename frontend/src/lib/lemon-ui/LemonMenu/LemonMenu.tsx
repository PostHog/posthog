import React, { FunctionComponent, ReactNode, useCallback, useMemo } from 'react'

import { KeyboardShortcut, KeyboardShortcutProps } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'
import { LemonDropdown, LemonDropdownProps } from '../LemonDropdown'
import { LemonTag } from '../LemonTag'
import { TooltipProps } from '../Tooltip'
import { useKeyboardNavigation } from './useKeyboardNavigation'

type KeyboardShortcut = Array<keyof KeyboardShortcutProps>

export interface LemonMenuItemBase
    extends Pick<
        LemonButtonProps,
        | 'icon'
        | 'sideIcon'
        | 'sideAction'
        | 'disabledReason'
        | 'tooltip'
        | 'tooltipPlacement'
        | 'active'
        | 'status'
        | 'data-attr'
        | 'size'
    > {
    label: string | JSX.Element
    key?: React.Key
    /** @deprecated You're probably doing something wrong if you're setting per-item classes. */
    className?: string
    /** True if the item is a custom element. */
    custom?: boolean
}
export interface LemonMenuItemNode extends LemonMenuItemBase {
    items: (LemonMenuItem | false | null)[]
    placement?: LemonDropdownProps['placement']
    keyboardShortcut?: never
}

export interface LemonMenuItemLeafCallback extends LemonMenuItemBase {
    onClick?: (e: React.MouseEvent) => void
    items?: never
    placement?: never
    keyboardShortcut?: KeyboardShortcut
}
export interface LemonMenuItemLeafLink extends LemonMenuItemBase {
    onClick?: (e: React.MouseEvent) => void
    to: string
    disableClientSideRouting?: boolean
    targetBlank?: boolean
    items?: never
    placement?: never
    keyboardShortcut?: KeyboardShortcut
}

export type LemonMenuItemLeaf = LemonMenuItemLeafCallback | LemonMenuItemLeafLink

export interface LemonMenuItemCustom {
    /** A label that's a component means it will be rendered directly, and not wrapped in a button. */
    label: () => JSX.Element
    key?: React.Key
    active?: never
    items?: never
    keyboardShortcut?: never

    /** True if the item is a custom element. */
    custom?: boolean
    placement?: never
}
export type LemonMenuItem = (LemonMenuItemLeaf | LemonMenuItemCustom | LemonMenuItemNode) & {
    tag?: 'alpha' | 'beta' | 'new'
}

export interface LemonMenuSection {
    title?: string | React.ReactNode
    key?: React.Key
    items: (LemonMenuItem | false | null)[]
    footer?: string | React.ReactNode
}

export type LemonMenuItems = (LemonMenuItem | LemonMenuSection | false | null)[]

export interface LemonMenuProps
    extends Pick<
            LemonDropdownProps,
            | 'placement'
            | 'fallbackPlacements'
            | 'matchWidth'
            | 'maxContentWidth'
            | 'visible'
            | 'onVisibilityChange'
            | 'closeOnClickInside'
            | 'closeParentPopoverOnClickInside'
            | 'className'
            | 'onClickOutside'
            | 'middleware'
            | 'startVisible'
        >,
        LemonMenuOverlayProps {
    /** Must support `ref` and `onKeyDown` for keyboard navigation. */
    children: React.ReactElement
    /** Index of the active (e.g. selected) item, if there is a specific one. */
    activeItemIndex?: number
    /**
     * If focus-based keyboard navigation is disabled, you must implement your own.
     * This is for cases of purpose-specific keyboard navigation, e.g. for a command palette.
     * `activeItemIndex` will still be used, but only to visually highlight the active item.
     * @default true
     */
    focusBasedKeyboardNavigation?: boolean
}

export function LemonMenu({
    items,
    activeItemIndex,
    tooltipPlacement,
    onVisibilityChange,
    focusBasedKeyboardNavigation = true,
    ...dropdownProps
}: LemonMenuProps): JSX.Element {
    const { referenceRef, itemsRef } = useKeyboardNavigation<HTMLElement, HTMLButtonElement>(
        items.flatMap((item) => (item && isLemonMenuSection(item) ? item.items : item)).length,
        activeItemIndex,
        { enabled: focusBasedKeyboardNavigation }
    )

    const _onVisibilityChange = useCallback(
        (visible: boolean) => {
            onVisibilityChange?.(visible)
            if (visible && activeItemIndex && activeItemIndex > -1) {
                // Scroll the active item into view once the menu is open (i.e. in the next tick)
                setTimeout(() => itemsRef?.current?.[activeItemIndex]?.current?.scrollIntoView({ block: 'center' }), 0)
            }
        },
        // no need to update this when itemsRef changes
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [onVisibilityChange, activeItemIndex]
    )

    return (
        <LemonDropdown
            overlay={
                <LemonMenuOverlay
                    buttonSize={dropdownProps.buttonSize || 'small'}
                    items={items}
                    tooltipPlacement={tooltipPlacement}
                    itemsRef={itemsRef}
                />
            }
            closeOnClickInside
            referenceRef={referenceRef}
            onVisibilityChange={_onVisibilityChange}
            {...dropdownProps}
        />
    )
}

export interface LemonMenuOverlayProps {
    items: LemonMenuItems
    tooltipPlacement?: TooltipProps['placement']
    itemsRef?: React.RefObject<React.RefObject<HTMLButtonElement>[]>
    /** @default 'small' */
    buttonSize?: 'xsmall' | 'small' | 'medium'
}

export function LemonMenuOverlay({
    items,
    tooltipPlacement = 'right',
    itemsRef,
    buttonSize = 'small',
}: LemonMenuOverlayProps): JSX.Element {
    const sectionsOrItems = useMemo(() => normalizeItems(items), [items])

    return sectionsOrItems.length > 0 && isLemonMenuSection(sectionsOrItems[0]) ? (
        <LemonMenuSectionList
            sections={sectionsOrItems as LemonMenuSection[]}
            buttonSize={buttonSize}
            tooltipPlacement={tooltipPlacement}
            itemsRef={itemsRef}
        />
    ) : (
        <LemonMenuItemList
            items={sectionsOrItems as LemonMenuItem[]}
            buttonSize={buttonSize}
            tooltipPlacement={tooltipPlacement}
            itemsRef={itemsRef}
            itemIndexOffset={0}
        />
    )
}

interface LemonMenuSectionListProps {
    sections: LemonMenuSection[]
    buttonSize: 'xsmall' | 'small' | 'medium'
    tooltipPlacement: TooltipProps['placement'] | undefined
    itemsRef: React.RefObject<React.RefObject<HTMLButtonElement>[]> | undefined
}

export function LemonMenuSectionList({
    sections,
    buttonSize,
    tooltipPlacement,
    itemsRef,
}: LemonMenuSectionListProps): JSX.Element {
    let rollingItemIndex = 0

    return (
        <ul>
            {sections.map((section, i) => {
                const sectionElement = (
                    <li key={section.key || i}>
                        <section className="deprecated-space-y-px">
                            {section.title ? (
                                typeof section.title === 'string' ? (
                                    <h5 className="mx-2 my-1">{section.title}</h5>
                                ) : (
                                    section.title
                                )
                            ) : null}
                            <LemonMenuItemList
                                items={section.items.filter(Boolean) as LemonMenuItem[]}
                                buttonSize={buttonSize}
                                tooltipPlacement={tooltipPlacement}
                                itemsRef={itemsRef}
                                itemIndexOffset={rollingItemIndex}
                            />
                            {section.footer ? <div>{section.footer}</div> : null}
                        </section>
                        {i < sections.length - 1 ? (
                            <LemonDivider className={buttonSize === 'small' ? 'my-1' : 'my-2'} />
                        ) : null}
                    </li>
                )
                rollingItemIndex += section.items.length
                return sectionElement
            })}
        </ul>
    )
}

interface LemonMenuItemListProps {
    items: LemonMenuItem[]
    buttonSize?: 'xsmall' | 'small' | 'medium'
    tooltipPlacement?: TooltipProps['placement'] | undefined
    itemsRef?: React.RefObject<React.RefObject<HTMLButtonElement>[]> | undefined
    itemIndexOffset?: number
}

export function LemonMenuItemList({
    items,
    buttonSize = 'small',
    itemIndexOffset = 0,
    tooltipPlacement = 'right',
    itemsRef,
}: LemonMenuItemListProps): JSX.Element {
    return (
        <ul className="deprecated-space-y-px">
            {items.map((item, itemIndex) => (
                <li key={item.key || itemIndex}>
                    <LemonMenuItemButton
                        item={item}
                        size={buttonSize}
                        tooltipPlacement={tooltipPlacement}
                        ref={itemsRef?.current?.[itemIndexOffset + itemIndex]}
                        tag={item.tag}
                        active={item.active}
                    />
                </li>
            ))}
        </ul>
    )
}

interface LemonMenuItemButtonProps {
    item: LemonMenuItem
    size: 'xsmall' | 'small' | 'medium'
    tooltipPlacement: TooltipProps['placement'] | undefined
    tag?: 'alpha' | 'beta' | 'new'
    active?: boolean
}

const LemonMenuItemButton: FunctionComponent<LemonMenuItemButtonProps & React.RefAttributes<HTMLButtonElement>> =
    React.forwardRef(
        (
            {
                item: { label, items, placement, keyboardShortcut, tag, custom, ...buttonProps },
                size,
                tooltipPlacement,
                active,
            },
            ref
        ): JSX.Element => {
            const Label = typeof label === 'function' ? label : null
            const button = Label ? (
                <Label key="x" />
            ) : (
                // @ts-expect-error - We don't have a type-level guarantee that `sideAction` won't be present
                // alongside `sideIcon` in one menu item, but that's fine. It'd be horribly complex to implement here.
                <LemonButton
                    ref={ref}
                    tooltipPlacement={tooltipPlacement}
                    fullWidth
                    role="menuitem"
                    size={size}
                    {...buttonProps}
                    active={active}
                >
                    {label as ReactNode}
                    {keyboardShortcut && (
                        <div className="-mr-0.5 inline-flex grow justify-end">
                            {/* Show the keyboard shortcut on the right */}
                            <KeyboardShortcut {...Object.fromEntries(keyboardShortcut.map((key) => [key, true]))} />
                        </div>
                    )}
                    {tag && (
                        <LemonTag
                            type={tag === 'alpha' ? 'completion' : tag === 'beta' ? 'warning' : 'success'}
                            size="small"
                            className="ml-2"
                        >
                            {tag.toUpperCase()}
                        </LemonTag>
                    )}
                </LemonButton>
            )

            return items ? (
                <LemonMenu
                    items={items}
                    tooltipPlacement={tooltipPlacement}
                    placement={placement || 'right-start'}
                    closeOnClickInside={!custom}
                    closeParentPopoverOnClickInside={!custom}
                    buttonSize={size}
                >
                    {button}
                </LemonMenu>
            ) : (
                button
            )
        }
    )
LemonMenuItemButton.displayName = 'LemonMenuItemButton'

function normalizeItems(sectionsAndItems: LemonMenuItems): LemonMenuItem[] | LemonMenuSection[] {
    const sections: LemonMenuSection[] = []
    let implicitSection: LemonMenuSection = { items: [] }
    for (const sectionOrItem of sectionsAndItems) {
        if (!sectionOrItem) {
            continue // Ignore falsy items
        }
        if (isLemonMenuSection(sectionOrItem)) {
            if (implicitSection.items.length > 0) {
                sections.push(implicitSection)
                implicitSection = { items: [] }
            }
            sections.push(sectionOrItem)
        } else {
            implicitSection.items.push(sectionOrItem)
        }
    }
    if (implicitSection.items.length > 0) {
        sections.push(implicitSection)
    }

    if (sections.length === 1 && !sections[0].title && !sections[0].footer) {
        return sections[0].items.filter(Boolean) as LemonMenuItem[]
    }
    return sections
}

export function isLemonMenuSection(candidate: LemonMenuSection | LemonMenuItem): candidate is LemonMenuSection {
    return candidate && 'items' in candidate && !('label' in candidate)
}
