import React, { FunctionComponent, useMemo } from 'react'
import { LemonButton, LemonButtonProps, LemonButtonWithDropdown } from '../LemonButton'
import { TooltipProps } from '../Tooltip'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { LemonDivider } from '../LemonDivider'

export interface LemonMenuItemBase
    extends Pick<
        LemonButtonProps,
        'icon' | 'sideIcon' | 'disabledReason' | 'tooltip' | 'active' | 'status' | 'data-attr'
    > {
    label: string | JSX.Element
}
interface LemonMenuItemNode extends LemonMenuItemBase {
    items: LemonMenuItemLeaf[]
}
interface LemonMenuItemLeaf extends LemonMenuItemBase {
    onClick: () => void
}
export type LemonMenuItem = LemonMenuItemLeaf | LemonMenuItemNode

export interface LemonMenuSection {
    title?: string
    items: LemonMenuItem[]
    footer?: string | React.ReactNode
}

export type LemonMenuItems = LemonMenuItemLeaf[] | LemonMenuSection[]

export interface LemonMenuProps {
    items: LemonMenuItems
    tooltipPlacement?: TooltipProps['placement']
}

export function LemonMenu({ items, tooltipPlacement }: LemonMenuProps): JSX.Element {
    const sections = useMemo(() => standardizeIntoSections(items), [items])

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
                                    <LemonMenuItemButton item={item} tooltipPlacement={tooltipPlacement} />
                                </li>
                            ))}
                        </ul>
                        {section.footer ? <ul>{section.footer}</ul> : null}
                    </section>
                    {i < sections.length - 1 ? <LemonDivider /> : null}
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
        const commonProps: Partial<LemonButtonProps> & React.RefAttributes<HTMLButtonElement> = {
            ref,
            children: item.label,
            tooltipPlacement,
            status: 'stealth',
            fullWidth: true,
            ...item,
        }
        return 'items' in item ? (
            <LemonButtonWithDropdown
                dropdown={{
                    overlay: <LemonMenu items={item.items} tooltipPlacement={tooltipPlacement} />,
                    placement: 'right-start',
                    actionable: true,
                    closeParentPopoverOnClickInside: true,
                }}
                {...commonProps}
            />
        ) : (
            <LemonButton {...commonProps} />
        )
    })
LemonMenuItemButton.displayName = 'LemonMenuItemRow'

function standardizeIntoSections(sectionsAndItems: LemonMenuSection[] | LemonMenuItemLeaf[]): LemonMenuSection[] {
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

function isLemonMenuSection(candidate: LemonMenuSection | LemonMenuItem): candidate is LemonMenuSection {
    return candidate && 'items' in candidate && !('label' in candidate)
}
