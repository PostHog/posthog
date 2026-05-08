import { ReactNode } from 'react'

import { Button } from '@posthog/quill'

import { useGroupList } from '../hooks/useGroupList'
import { TaxonomicFilterGroup } from '../types'
import { useTaxonomicFilterContext } from './context'

export interface TaxonomicFilterCategoriesProps {
    /** Override how each tab is rendered. */
    renderTab?: (props: TaxonomicFilterCategoryRenderProps) => ReactNode
    className?: string
}

export interface TaxonomicFilterCategoryRenderProps {
    group: TaxonomicFilterGroup
    isActive: boolean
    count: number
    isLoading: boolean
    onSelect: () => void
}

export function TaxonomicFilterCategories({ renderTab, className }: TaxonomicFilterCategoriesProps): JSX.Element {
    const { groups } = useTaxonomicFilterContext()
    return (
        <div className={className} role="tablist">
            {groups.map((group) => (
                <TaxonomicFilterCategoryTab key={group.type} group={group} renderTab={renderTab} />
            ))}
        </div>
    )
}

interface CategoryTabProps {
    group: TaxonomicFilterGroup
    renderTab?: (props: TaxonomicFilterCategoryRenderProps) => ReactNode
}

function TaxonomicFilterCategoryTab({ group, renderTab }: CategoryTabProps): JSX.Element {
    const { activeGroupType, setActiveGroupType, getGroupListInput } = useTaxonomicFilterContext()
    const list = useGroupList(getGroupListInput(group))
    const isActive = activeGroupType === group.type
    const onSelect = (): void => setActiveGroupType(group.type)

    if (renderTab) {
        return (
            <>
                {renderTab({
                    group,
                    isActive,
                    count: list.totalResultCount,
                    isLoading: list.isLoading,
                    onSelect,
                })}
            </>
        )
    }

    return (
        <Button
            type="button"
            role="tab"
            data-attr={`taxonomic-tab-${group.type}`}
            aria-selected={isActive}
            variant={isActive ? 'primary' : 'outline'}
            size="sm"
            onClick={onSelect}
        >
            {group.categoryLabel ? (
                group.categoryLabel(list.totalResultCount)
            ) : (
                <>
                    {group.name}
                    {!list.needsMoreSearchCharacters && `: ${list.isLoading ? '…' : list.totalResultCount}`}
                </>
            )}
        </Button>
    )
}
