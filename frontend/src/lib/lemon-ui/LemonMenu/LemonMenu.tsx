import React, { FunctionComponent, useMemo } from 'react'
import { LemonButton, LemonButtonProps } from '../LemonButton'
import { TooltipProps } from '../Tooltip'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { LemonDivider } from '../LemonDivider'
import { LemonDropdown, LemonDropdownProps } from '../LemonDropdown'
import { useKeyboardNavigation } from './useKeyboardNavigation'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
export type LemonMenuItemLeaf =
    | (LemonMenuItemBase & {
          onClick: () => void
      })
    | (LemonMenuItemBase & {
          to: string
      })
    | (LemonMenuItemBase & {
          onClick: () => void
          to: string
      })
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
            | 'onVisibilityChange'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const sections = useMemo(() => standardizeIntoSections(items), [items])

    const buttonSize = featureFlags[FEATURE_FLAGS.POSTHOG_3000] ? 'small' : 'medium'

    let rollingItemIndex = 0
    return (
        <ul>
            {sections.map((section, i) => (
                <li key={i}>
                    <section className="space-y-px">
                        {section.title ? (
                            typeof section.title === 'string' ? (
                                <h5>{section.title}</h5>
                            ) : (
                                section.title
                            )
                        ) : null}
                        <ul className="space-y-px">
                            {section.items.map((item, index) => (
                                <li key={index}>
                                    <LemonMenuItemButton
                                        item={item}
                                        size={buttonSize}
                                        tooltipPlacement={tooltipPlacement}
                                        ref={itemsRef?.current?.[rollingItemIndex++]}
                                    />
                                </li>
                            ))}
                        </ul>
                        {section.footer ? <ul>{section.footer}</ul> : null}
                    </section>
                    {i < sections.length - 1 ? (
                        <LemonDivider className={buttonSize === 'small' ? 'my-1' : 'my-2'} />
                    ) : null}
                </li>
            ))}
        </ul>
    )
}

interface LemonMenuItemButtonProps {
    item: LemonMenuItem
    size: 'small' | 'medium'
    tooltipPlacement: TooltipPlacement | undefined
}

const LemonMenuItemButton: FunctionComponent<LemonMenuItemButtonProps & React.RefAttributes<HTMLButtonElement>> =
    React.forwardRef(({ item, size, tooltipPlacement }, ref): JSX.Element => {
        const button = (
            <LemonButton
                ref={ref}
                tooltipPlacement={tooltipPlacement}
                status="stealth"
                fullWidth
                role="menuitem"
                size={size}
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

function standardizeIntoSections(sectionsAndItems: (LemonMenuItem | LemonMenuSection)[]): LemonMenuSection[] {
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

    return sections
}

export function isLemonMenuSection(candidate: LemonMenuSection | LemonMenuItem): candidate is LemonMenuSection {
    return candidate && 'items' in candidate && !('label' in candidate)
}
