import { LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { cn } from 'lib/utils/css-classes'

import { TaxonomicFilterEmptyState, taxonomicFilterGroupTypesWithEmptyStates } from './TaxonomicFilterEmptyState'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'

// Number of taxonomic groups after which we switch to vertical layout by default
const VERTICAL_LAYOUT_THRESHOLD = 4

export interface InfiniteSelectResultsProps {
    focusInput: () => void
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    popupAnchorElement: HTMLDivElement | null
    useVerticalLayout?: boolean
}

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
    const logic = infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: groupType })
    const { taxonomicGroups } = useValues(taxonomicFilterLogic)
    const { totalResultCount, totalListCount, isLoading, results, hasRemoteDataSource } = useValues(logic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    // :TRICKY: use `totalListCount` (results + extra) to toggle interactivity, while showing `totalResultCount`
    const canInteract = totalListCount > 0 || taxonomicFilterGroupTypesWithEmptyStates.includes(groupType)
    const hasOnlyDefaultItems = results?.length === 1 && (!results[0].id || results[0].id === '')
    const showLoading = isLoading && (!results || results.length === 0 || hasOnlyDefaultItems) && hasRemoteDataSource

    return (
        <LemonTag
            type={isActive ? 'primary' : canInteract ? 'option' : 'muted'}
            data-attr={`taxonomic-tab-${groupType}`}
            onClick={canInteract ? onClick : undefined}
            disabledReason={!canInteract ? 'No results' : null}
            className="font-normal"
        >
            {group?.render ? (
                group?.name
            ) : (
                <>
                    {group?.name}
                    {': '}
                    {showLoading ? (
                        <Spinner className="text-sm inline-block ml-1" textColored speed="0.8s" />
                    ) : (
                        totalResultCount
                    )}
                </>
            )}
        </LemonTag>
    )
}

export function InfiniteSelectResults({
    focusInput,
    taxonomicFilterLogicProps,
    popupAnchorElement,
    useVerticalLayout: useVerticalLayoutProp,
}: InfiniteSelectResultsProps): JSX.Element {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes, activeTaxonomicGroup, value } =
        useValues(taxonomicFilterLogic)

    const openTab = activeTab || taxonomicGroups[0].type
    const logic = infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: openTab })

    const { setActiveTab, selectItem } = useActions(taxonomicFilterLogic)

    const { totalListCount, items } = useValues(logic)

    const RenderComponent = activeTaxonomicGroup?.render

    const hasMultipleGroups = taxonomicGroupTypes.length > 1

    const listComponent = RenderComponent ? (
        <RenderComponent
            {...(activeTaxonomicGroup?.componentProps ?? {})}
            value={value}
            onChange={(newValue, item) => selectItem(activeTaxonomicGroup, newValue, item, items.originalQuery)}
        />
    ) : (
        <>
            {hasMultipleGroups && (
                <div className="taxonomic-group-title pb-2">
                    {taxonomicGroups.find((g) => g.type === openTab)?.name || openTab}
                </div>
            )}
            <InfiniteList popupAnchorElement={popupAnchorElement} />
        </>
    )

    const showEmptyState = totalListCount === 0 && taxonomicFilterGroupTypesWithEmptyStates.includes(openTab)

    const useVerticalLayout =
        useVerticalLayoutProp !== undefined
            ? useVerticalLayoutProp
            : taxonomicGroupTypes.length > VERTICAL_LAYOUT_THRESHOLD

    return (
        <div className={cn('flex h-full', useVerticalLayout ? 'flex-row' : 'flex-col')}>
            {hasMultipleGroups && (
                <div
                    className={cn(
                        useVerticalLayout ? 'border-r pr-2 mr-2 flex-shrink-0' : 'border-b mb-2',
                        'border-primary'
                    )}
                >
                    <div className="taxonomic-group-title">Categories</div>
                    <div
                        className={cn(
                            'taxonomic-pills flex',
                            useVerticalLayout ? 'flex-col gap-1' : 'gap-0.5 flex-wrap'
                        )}
                    >
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
                                {showEmptyState && <TaxonomicFilterEmptyState groupType={groupType} />}
                                {!showEmptyState && listComponent}
                            </BindLogic>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
