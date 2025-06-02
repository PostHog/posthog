import { useValues } from 'kea'
import { router } from 'kea-router'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { CustomMenuProps } from '../types'

export function ProductAnalyticsMenu({ MenuItem, MenuSeparator }: CustomMenuProps): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)

    function handleRouting(href?: string): void {
        if (href) {
            router.actions.push(href)
        }
    }

    return (
        <>
            {treeItemsNew
                .find(({ name }) => name === 'Insight')
                ?.children?.sort((a, b) => (a.visualOrder ?? 0) - (b.visualOrder ?? 0))
                ?.map((child) => (
                    <MenuItem
                        key={child.id}
                        asChild
                        onClick={() => {
                            handleRouting(
                                typeof child.record?.href === 'function'
                                    ? child.record?.href(child.record?.ref)
                                    : child.record?.href
                            )
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                                handleRouting(
                                    typeof child.record?.href === 'function'
                                        ? child.record?.href(child.record?.ref)
                                        : child.record?.href
                                )
                                // small delay to fight dropdown menu from taking focus
                                setTimeout(() => {
                                    mainContentRef?.current?.focus()
                                }, 10)
                            }
                        }}
                    >
                        <ButtonPrimitive menuItem>
                            {child.icon}
                            New {child.name.toLowerCase()}
                        </ButtonPrimitive>
                    </MenuItem>
                ))}
            <MenuSeparator />
        </>
    )
}
