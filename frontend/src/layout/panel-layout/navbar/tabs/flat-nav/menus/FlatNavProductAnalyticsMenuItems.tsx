import { useValues } from 'kea'

import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel } from '@posthog/quill'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import { FlatNavMenuLinkItem } from './FlatNavMenuLinkItem'

export function FlatNavProductAnalyticsMenuItems(): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)

    const insightTypes = [...(treeItemsNew.find(({ name }) => name === 'Insight')?.children ?? [])].sort(
        (a, b) => (a.visualOrder ?? 0) - (b.visualOrder ?? 0)
    )

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Create new insight type</DropdownMenuLabel>
            {insightTypes.length === 0 ? (
                <DropdownMenuItem disabled>No insight types available</DropdownMenuItem>
            ) : (
                insightTypes.map((insightType) => (
                    <FlatNavMenuLinkItem key={insightType.id} to={insightType.record?.href} icon={insightType.icon}>
                        {insightType.name}
                    </FlatNavMenuLinkItem>
                ))
            )}
        </DropdownMenuGroup>
    )
}
