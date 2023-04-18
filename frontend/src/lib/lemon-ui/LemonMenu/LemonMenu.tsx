import React, { FunctionComponent, useMemo } from 'react'
import { LemonButton, LemonButtonProps } from '../LemonButton'
import { TooltipProps } from '../Tooltip'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { LemonDivider } from '../LemonDivider'
import { LemonDropdown, LemonDropdownProps } from '../LemonDropdown'
import { useKeyboardNavigation } from './useKeyboardNavigation'

export interface LemonMenuItemBase
    extends Pick<
        LemonButtonProps,
        'icon' | 'sideIcon' | 'disabledReason' | 'tooltip' | 'active' | 'status' | 'data-attr'
    > {
    label: string | JSX.Element
}
export interface LemonMenuItemNode extends LemonMenuItemBase {
    items: LemonMenuItemLeaf[]
}
export interface LemonMenuItemLeaf extends LemonMenuItemBase {
    onClick: () => void
}
export type LemonMenuItem = LemonMenuItemLeaf | LemonMenuItemNode

export interface LemonMenuSection {
    title?: string | React.ReactNode
    items: LemonMenuItem[]
    footer?: string | React.ReactNode
}

export type LemonMenuItems = (LemonMenuItem | LemonMenuSection)[]

export interface LemonMenuProps
    extends Pick<
            LemonDropdownProps,
            | 'placement'
            | 'fallbackPlacements'
            | 'actionable'
            | 'sameWidth'
            | 'maxContentWidth'
            | 'visible'
            | 'closeParentPopoverOnClickInside'
            | 'className'
        >,
        LemonMenuOverlayProps {
    /** Must support `ref` and `onKeyDown` for keyboard navigation. */
    children: React.ReactElement
    /** Optional index of the active (e.g. selected) item. This improves the keyboard navigation experience. */
    activeItemIndex?: number
}

export function LemonMenu({ items, activeItemIndex, tooltipPlacement, ...dropdownProps }: LemonMenuProps): JSX.Element {
    const { referenceRef, itemsRef } = useKeyboardNavigation<HTMLElement, HTMLButtonElement>(
        items.flatMap((item) => (isLemonMenuSection(item) ? item.items : item)).length,
        activeItemIndex
    )

    return (
        <LemonDropdown
            overlay={<LemonMenuOverlay items={items} tooltipPlacement={tooltipPlacement} itemsRef={itemsRef} />}
            closeOnClickInside
            referenceRef={referenceRef}
            {...dropdownProps}
        />
    )
}

export interface LemonMenuOverlayProps {
    items: LemonMenuItems
    tooltipPlacement?: TooltipProps['placement']
    itemsRef?: React.RefObject<React.RefObject<HTMLButtonElement>[]>
}

export function LemonMenuOverlay({ items, tooltipPlacement, itemsRef }: LemonMenuOverlayProps): JSX.Element {
    const sectionsOrItems = useMemo(() => normalizeItems(items), [items])

    return sectionsOrItems.length > 0 && isLemonMenuSection(sectionsOrItems[0]) ? (
        <LemonMenuSectionList
            sections={sectionsOrItems as LemonMenuSection[]}
            tooltipPlacement={tooltipPlacement}
            itemsRef={itemsRef}
        />
    ) : (
        <LemonMenuItemList
            items={sectionsOrItems as LemonMenuItem[]}
            tooltipPlacement={tooltipPlacement}
            itemsRef={itemsRef}
            itemIndexOffset={0}
        />
    )
}

interface LemonMenuSectionListProps {
    sections: LemonMenuSection[]
    tooltipPlacement: TooltipPlacement | undefined
    itemsRef: React.RefObject<React.RefObject<HTMLButtonElement>[]> | undefined
}

export function LemonMenuSectionList({ sections, tooltipPlacement, itemsRef }: LemonMenuSectionListProps): JSX.Element {
    let rollingItemIndex = 0

    return (
        <ul>
            {sections.map((section, i) => {
                const sectionElement = (
                    <li key={i}>
                        <section className="space-y-px">
                            {section.title ? (
                                typeof section.title === 'string' ? (
                                    <h5>{section.title}</h5>
                                ) : (
                                    section.title
                                )
                            ) : null}
                            <LemonMenuItemList
                                items={section.items}
                                tooltipPlacement={tooltipPlacement}
                                itemsRef={itemsRef}
                                itemIndexOffset={rollingItemIndex}
                            />
                            {section.footer ? <ul>{section.footer}</ul> : null}
                        </section>
                        {i < sections.length - 1 ? <LemonDivider /> : null}
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
    tooltipPlacement: TooltipPlacement | undefined
    itemsRef: React.RefObject<React.RefObject<HTMLButtonElement>[]> | undefined
    itemIndexOffset?: number
}

export function LemonMenuItemList({
    items,
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
    tooltipPlacement: TooltipPlacement | undefined
}

const LemonMenuItemButton: FunctionComponent<LemonMenuItemButtonProps & React.RefAttributes<HTMLButtonElement>> =
    React.forwardRef(({ item, tooltipPlacement }, ref): JSX.Element => {
        const button = (
            <LemonButton
                ref={ref}
                tooltipPlacement={tooltipPlacement}
                status="stealth"
                fullWidth
                role="menuitem"
                {...item}
            >
                {item.label}
            </LemonButton>
        )

        return 'items' in item ? (
            <LemonMenu items={item.items} tooltipPlacement={tooltipPlacement} placement="right-start" actionable>
                {button}
            </LemonMenu>
        ) : (
            button
        )
    })
LemonMenuItemButton.displayName = 'LemonMenuItemButton'

function normalizeItems(sectionsAndItems: (LemonMenuItem | LemonMenuSection)[]): LemonMenuItem[] | LemonMenuSection[] {
    const sections: LemonMenuSection[] = []
    let implicitSection: LemonMenuSection = { items: [] }
    for (const sectionOrItem of sectionsAndItems) {
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
        return sections[0].items
    }
    return sections
}

export function isLemonMenuSection(candidate: LemonMenuSection | LemonMenuItem): candidate is LemonMenuSection {
    return candidate && 'items' in candidate && !('label' in candidate)
}
