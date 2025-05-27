import { useValues } from 'kea'
import { router } from 'kea-router'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import { CustomMenuProps } from '../types'

export function ProductAnalyticsMenu({ MenuItem, MenuSeparator }: CustomMenuProps): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)

    return (
        <>
            {treeItemsNew
                .find(({ name }) => name === 'Insight')
                ?.children?.map((child) => (
                    <MenuItem
                        key={child.id}
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            if (child.record?.href) {
                                router.actions.push(
                                    typeof child.record.href === 'function'
                                        ? child.record.href(child.record.ref)
                                        : child.record.href
                                )
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
