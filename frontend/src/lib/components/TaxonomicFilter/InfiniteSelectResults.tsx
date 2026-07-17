import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import {
    CategoryDropdownVariant,
    DefinitionPopoverRenderer,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { TaxonomicFilterEmptyState, taxonomicFilterGroupTypesWithEmptyStates } from './TaxonomicFilterEmptyState'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'

export interface InfiniteSelectResultsProps {
    focusInput: () => void
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    popupAnchorElement: HTMLDivElement | null
    definitionPopoverRenderer?: DefinitionPopoverRenderer
    categoryDropdownVariant?: CategoryDropdownVariant
}

export function getCategoryPillDisabledReason(
    canInteract: boolean,
    groupType: TaxonomicFilterGroupType,
    hasPathsAdvanced: boolean
): string | null {
    if (canInteract) {
        return null
    }
    // Wildcard groups (paths) are gated behind Advanced paths — explain the paygate rather than a generic "No results".
    // Paid users with no wildcards defined still see "No results" since they can add them.
    if (groupType === TaxonomicFilterGroupType.Wildcards && !hasPathsAdvanced) {
        return 'Wildcard groups are only available on paid plans'
    }
    return 'No results'
}

// CategoryPillContent uses useValues(infiniteListLogic) without props, relying on BindLogic context
// This ensures proper logic mounting and prevents "Can not find path" KEA errors
function CategoryPillContent({
    isActive,
    groupType,
    onClick,
}: {
    isActive: boolean
    groupType: TaxonomicFilterGroupType
    onClick: () => void
}): JSX.Element {
    const { taxonomicGroups } = useValues(taxonomicFilterLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const {
        totalResultCount,
        totalListCount,
        isLoading,
        isLocalDataLoading,
        hasRemoteDataSource,
        hasMore,
        needsMoreSearchCharacters,
    } = useValues(infiniteListLogic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    // :TRICKY: use `totalListCount` (results + extra) to toggle interactivity, while showing `totalResultCount`
    const canInteract =
        totalListCount > 0 ||
        taxonomicFilterGroupTypesWithEmptyStates.includes(groupType) ||
        groupType === TaxonomicFilterGroupType.SuggestedFilters
    const showLoading = (isLoading && hasRemoteDataSource) || isLocalDataLoading

    const hasPathsAdvanced = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const disabledReason = getCategoryPillDisabledReason(canInteract, groupType, hasPathsAdvanced)
    // Wildcard groups are gated behind Advanced paths. LemonTag's `disabledReason` only renders as a slow
    // native `title`, so surface the upgrade hint via a proper Tooltip (below) instead. Other groups keep the
    // existing `disabledReason` ("No results") behavior.
    const isGatedWildcards = !canInteract && groupType === TaxonomicFilterGroupType.Wildcards && !hasPathsAdvanced

    const tag = (
        <LemonTag
            type={isActive ? 'primary' : canInteract ? 'option' : 'muted'}
            data-attr={`taxonomic-tab-${groupType}`}
            onClick={canInteract ? onClick : undefined}
            disabledReason={disabledReason}
            className="font-normal"
            // For the gated case the reason is shown via the Tooltip below, so suppress LemonTag's native `title`
            // to avoid a duplicate tooltip while keeping its disabled semantics (aria-disabled, cursor, styling).
            // aria-label keeps the reason screen-reader-accessible since the suppressed title no longer can.
            {...(isGatedWildcards ? { title: '', 'aria-label': disabledReason ?? undefined } : {})}
        >
            {group?.categoryLabel ? (
                group.categoryLabel(totalResultCount)
            ) : (
                <>
                    {group?.name}
                    {!needsMoreSearchCharacters && (
                        <>
                            {': '}
                            {showLoading ? (
                                <Spinner className="text-sm inline-block ml-1" textColored speed="0.8s" />
                            ) : (
                                totalResultCount
                            )}
                            {/* This is a workaround. We need to make the logic fetch more results when querying from clickhouse*/}
                            <span aria-label={hasMore ? `${totalResultCount} or more` : `${totalResultCount}`}>
                                {hasMore ? '+' : ''}
                            </span>
                        </>
                    )}
                </>
            )}
        </LemonTag>
    )

    return isGatedWildcards && disabledReason ? <Tooltip title={disabledReason}>{tag}</Tooltip> : tag
}

// CategoryPill wraps CategoryPillContent with BindLogic to ensure infiniteListLogic is properly mounted
// before accessing its values. Without BindLogic, KEA throws "Can not find path" errors.
function CategoryPill({
    isActive,
    groupType,
    taxonomicFilterLogicProps,
    onClick,
}: {
    isActive: boolean
    groupType: TaxonomicFilterGroupType
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    onClick: () => void
}): JSX.Element {
    return (
        <BindLogic logic={infiniteListLogic} props={{ ...taxonomicFilterLogicProps, listGroupType: groupType }}>
            <CategoryPillContent isActive={isActive} groupType={groupType} onClick={onClick} />
        </BindLogic>
    )
}

function TaxonomicGroupTitle({ openTab }: { openTab: TaxonomicFilterGroupType }): JSX.Element {
    const { taxonomicGroups } = useValues(taxonomicFilterLogic)
    return (
        <div className="flex flex-row justify-between items-center w-full relative pb-2">
            {taxonomicGroups.find((g) => g.type === openTab)?.name || openTab}
        </div>
    )
}

export function InfiniteSelectResults({
    focusInput,
    taxonomicFilterLogicProps,
    popupAnchorElement,
    definitionPopoverRenderer,
    categoryDropdownVariant = 'control',
}: InfiniteSelectResultsProps): JSX.Element {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes, activeTaxonomicGroup, value } =
        useValues(taxonomicFilterLogic)
    const wrapperRef = useRef<HTMLDivElement | null>(null)

    const openTab = activeTab || taxonomicGroups[0].type
    const infiniteListLogicProps = { ...taxonomicFilterLogicProps, listGroupType: openTab }
    const logic = infiniteListLogic(infiniteListLogicProps)

    const { setActiveTab, selectItem } = useActions(taxonomicFilterLogic)
    const { reportTaxonomicFilterCategorySelected } = useActions(eventUsageLogic)

    const { totalListCount, isLocalDataLoading } = useValues(logic)

    const RenderComponent = activeTaxonomicGroup?.render

    const hasMultipleGroups = taxonomicGroupTypes.length > 1
    const showCategoryColumn = hasMultipleGroups && categoryDropdownVariant === 'control'

    const listComponent = RenderComponent ? (
        <RenderComponent
            {...(activeTaxonomicGroup?.componentProps ?? {})}
            value={value}
            onChange={(newValue, item) => selectItem(activeTaxonomicGroup, newValue, item)}
            infiniteListLogicProps={infiniteListLogicProps}
        />
    ) : (
        <>
            {hasMultipleGroups && (
                <div className="taxonomic-group-title">
                    <TaxonomicGroupTitle openTab={openTab} />
                </div>
            )}
            <InfiniteList
                popupAnchorElement={popupAnchorElement ?? wrapperRef.current}
                definitionPopoverRenderer={definitionPopoverRenderer}
            />
        </>
    )

    const showDataWarehouseLoadingState =
        (openTab === TaxonomicFilterGroupType.DataWarehouse ||
            openTab === TaxonomicFilterGroupType.DataWarehouseSourceTables ||
            openTab === TaxonomicFilterGroupType.DataWarehouseProperties) &&
        totalListCount === 0 &&
        isLocalDataLoading
    const showEmptyState =
        !showDataWarehouseLoadingState &&
        totalListCount === 0 &&
        taxonomicFilterGroupTypesWithEmptyStates.includes(openTab)

    return (
        <div ref={wrapperRef} className="flex flex-row h-full">
            {showCategoryColumn && (
                <div className="border-r pr-2 mr-2 flex-shrink-0 border-primary">
                    <div className="taxonomic-group-title">Categories</div>
                    <div className="taxonomic-pills flex flex-col gap-1">
                        {taxonomicGroupTypes.map((groupType) => {
                            return (
                                <CategoryPill
                                    key={groupType}
                                    groupType={groupType}
                                    taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                                    isActive={groupType === openTab}
                                    onClick={() => {
                                        setActiveTab(groupType)
                                        focusInput()
                                        reportTaxonomicFilterCategorySelected(
                                            groupType,
                                            taxonomicFilterLogicProps.eventNames?.[0]
                                        )
                                    }}
                                />
                            )
                        })}
                    </div>
                </div>
            )}

            <div className={cn('flex-1 overflow-hidden min-h-0')}>
                {taxonomicGroupTypes.map((groupType) => {
                    return (
                        <div key={groupType} className={cn(groupType === openTab ? 'flex flex-col h-full' : 'hidden')}>
                            <BindLogic
                                logic={infiniteListLogic}
                                props={{ ...taxonomicFilterLogicProps, listGroupType: groupType }}
                            >
                                {(showDataWarehouseLoadingState || showEmptyState) && (
                                    <TaxonomicFilterEmptyState
                                        groupType={groupType}
                                        isLoading={showDataWarehouseLoadingState}
                                    />
                                )}
                                {!showDataWarehouseLoadingState && !showEmptyState && listComponent}
                                {!showDataWarehouseLoadingState &&
                                    !showEmptyState &&
                                    (() => {
                                        const currentGroup = taxonomicGroups.find((g) => g.type === groupType)
                                        return (
                                            currentGroup?.footerMessage && (
                                                <div className="p-2 border-t border-border">
                                                    {currentGroup.footerMessage}
                                                </div>
                                            )
                                        )
                                    })()}
                            </BindLogic>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
