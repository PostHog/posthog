import React, { FunctionComponent, ReactNode, useCallback, useMemo } from 'react'

import { KeyboardShortcut, KeyboardShortcutProps } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'
import { LemonDropdown, LemonDropdownProps } from '../LemonDropdown'
import { TooltipProps } from '../Tooltip'
import { useKeyboardNavigation } from './useKeyboardNavigation'

type KeyboardShortcut = Array<keyof KeyboardShortcutProps>

export interface LemonMenuItemBase
    extends Pick<
        LemonButtonProps,
        'icon' | 'sideIcon' | 'disabledReason' | 'tooltip' | 'active' | 'status' | 'data-attr'
    > {
    label: string | JSX.Element
    /** True if the item is a custom element. */
    custom?: boolean
}
export interface LemonMenuItemNode extends LemonMenuItemBase {
    items: (LemonMenuItem | false | null)[]
    keyboardShortcut?: never
}
export type LemonMenuItemLeaf =
    | (LemonMenuItemBase & {
          onClick: () => void
          items?: never
          keyboardShortcut?: KeyboardShortcut
      })
    | (LemonMenuItemBase & {
          to: string
          disableClientSideRouting?: boolean
          targetBlank?: boolean
          items?: never
          keyboardShortcut?: KeyboardShortcut
      })
    | (LemonMenuItemBase & {
          onClick: () => void
          to: string
          disableClientSideRouting?: boolean
          targetBlank?: boolean
          items?: never
          keyboardShortcut?: KeyboardShortcut
      })
export interface LemonMenuItemCustom {
    /** A label that's a component means it will be rendered directly, and not wrapped in a button. */
    label: () => JSX.Element
    active?: never
    items?: never
    keyboardShortcut?: never
    /** True if the item is a custom element. */
    custom?: boolean
}
export type LemonMenuItem = LemonMenuItemLeaf | LemonMenuItemCustom | LemonMenuItemNode

export interface LemonMenuSection {
    title?: string | React.ReactNode
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
        >,
        LemonMenuOverlayProps {
    /** Must support `ref` and `onKeyDown` for keyboard navigation. */
    children: React.ReactElement
    /** Index of the active (e.g. selected) item, if there is a specific one. */
    activeItemIndex?: number
}

export function LemonMenu({
    items,
    activeItemIndex,
    tooltipPlacement,
    onVisibilityChange,
    ...dropdownProps
}: LemonMenuProps): JSX.Element {
    const { referenceRef, itemsRef } = useKeyboardNavigation<HTMLElement, HTMLButtonElement>(
        items.flatMap((item) => (item && isLemonMenuSection(item) ? item.items : item)).length,
        activeItemIndex
    )

    const _onVisibilityChange = useCallback(
        (visible: boolean) => {
            onVisibilityChange?.(visible)
            if (visible && activeItemIndex && activeItemIndex > -1) {
                // Scroll the active item into view once the menu is open (i.e. in the next tick)
                setTimeout(() => itemsRef?.current?.[activeItemIndex]?.current?.scrollIntoView({ block: 'center' }), 0)
            }
        },
        [onVisibilityChange, activeItemIndex]
    )

    return (
        <LemonDropdown
            overlay={<LemonMenuOverlay items={items} tooltipPlacement={tooltipPlacement} itemsRef={itemsRef} />}
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
    buttonSize?: 'small' | 'medium'
}

export function LemonMenuOverlay({
    items,
    tooltipPlacement,
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
    buttonSize: 'small' | 'medium'
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
                    <li key={i}>
                        <section className="space-y-px">
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
    buttonSize: 'small' | 'medium'
    tooltipPlacement: TooltipProps['placement'] | undefined
    itemsRef: React.RefObject<React.RefObject<HTMLButtonElement>[]> | undefined
    itemIndexOffset?: number
}

export function LemonMenuItemList({
    items,
    buttonSize,
    itemIndexOffset = 0,
    tooltipPlacement,
    itemsRef,
}: LemonMenuItemListProps): JSX.Element {
    let rollingItemIndex = 0

    return (
        <ul className="space-y-px">
            {items.map((item, index) => (
                <li key={index}>
                    <LemonMenuItemButton
                        item={item}
                        size={buttonSize}
                        tooltipPlacement={tooltipPlacement}
                        ref={itemsRef?.current?.[itemIndexOffset + rollingItemIndex++]}
                    />
                </li>
            ))}
        </ul>
    )
}

interface LemonMenuItemButtonProps {
    item: LemonMenuItem
    size: 'small' | 'medium'
    tooltipPlacement: TooltipProps['placement'] | undefined
}

const LemonMenuItemButton: FunctionComponent<LemonMenuItemButtonProps & React.RefAttributes<HTMLButtonElement>> =
    React.forwardRef(
        (
            { item: { label, items, keyboardShortcut, custom, ...buttonProps }, size, tooltipPlacement },
            ref
        ): JSX.Element => {
            const Label = typeof label === 'function' ? label : null
            const button = Label ? (
                <Label key="x" />
            ) : (
                <LemonButton
                    ref={ref}
                    tooltipPlacement={tooltipPlacement}
                    fullWidth
                    role="menuitem"
                    size={size}
                    {...buttonProps}
                >
                    {label as ReactNode}
                    {keyboardShortcut && (
                        <div className="-mr-0.5 inline-flex grow justify-end">
                            {/* Show the keyboard shortcut on the right */}
                            <KeyboardShortcut {...Object.fromEntries(keyboardShortcut.map((key) => [key, true]))} />
                        </div>
                    )}
                </LemonButton>
            )

            return items ? (
                <LemonMenu
                    items={items}
                    tooltipPlacement={tooltipPlacement}
                    placement="right-start"
                    closeOnClickInside={custom ? false : true}
                    closeParentPopoverOnClickInside={custom ? false : true}
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
