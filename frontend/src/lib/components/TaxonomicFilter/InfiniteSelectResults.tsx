import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { TaxonomicFilterEmptyState, taxonomicFilterGroupTypesWithEmptyStates } from './TaxonomicFilterEmptyState'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'

export interface InfiniteSelectResultsProps {
    focusInput: () => void
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    popupAnchorElement: HTMLDivElement | null
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
    const count = hasRemoteDataSource ? totalResultCount : results?.length || 0

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
                    {showLoading ? <Spinner className="text-sm inline-block ml-1" textColored speed="0.8s" /> : count}
                </>
            )}
        </LemonTag>
    )
}

export function InfiniteSelectResults({
    focusInput,
    taxonomicFilterLogicProps,
    popupAnchorElement,
}: InfiniteSelectResultsProps): JSX.Element {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes, activeTaxonomicGroup, value } =
        useValues(taxonomicFilterLogic)
    const logic = infiniteListLogic({ ...taxonomicFilterLogicProps, listGroupType: activeTab })

    const { setActiveTab, selectItem } = useActions(taxonomicFilterLogic)

    const { totalListCount } = useValues(logic)

    const RenderComponent = activeTaxonomicGroup?.render

    const openTab = activeTab || taxonomicGroups[0].type
    const hasMultipleGroups = taxonomicGroupTypes.length > 1

    const listComponent = RenderComponent ? (
        <RenderComponent
            {...(activeTaxonomicGroup?.componentProps ?? {})}
            value={value}
            onChange={(newValue, item) => selectItem(activeTaxonomicGroup, newValue, item)}
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

    return (
        <>
            {hasMultipleGroups && (
                <div className="border-b border-primary">
                    <div className="taxonomic-group-title">Categories</div>
                    <div className="taxonomic-pills flex gap-0.5 flex-wrap">
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

            {taxonomicGroupTypes.map((groupType) => {
                return (
                    <div key={groupType} className={clsx(groupType === openTab ? 'block' : 'hidden')}>
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
        </>
    )
}
