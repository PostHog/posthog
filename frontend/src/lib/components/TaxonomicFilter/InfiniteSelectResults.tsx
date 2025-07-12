import { IconCheck, IconSort } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { taxonomicFilterPreferencesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPreferencesLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { IconBlank } from 'lib/lemon-ui/icons'
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
    const { totalResultCount, totalListCount, isLoading, hasRemoteDataSource } = useValues(logic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    // :TRICKY: use `totalListCount` (results + extra) to toggle interactivity, while showing `totalResultCount`
    const canInteract = totalListCount > 0 || taxonomicFilterGroupTypesWithEmptyStates.includes(groupType)
    const showLoading = isLoading && hasRemoteDataSource

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

function TaxonomicGroupTitle({ openTab }: { openTab: TaxonomicFilterGroupType }): JSX.Element {
    const { taxonomicGroups } = useValues(taxonomicFilterLogic)

    const { eventOrdering } = useValues(taxonomicFilterPreferencesLogic)
    const { setEventOrdering } = useActions(taxonomicFilterPreferencesLogic)

    return (
        <div className="flex flex-row justify-between items-center w-full relative pb-2">
            {openTab === TaxonomicFilterGroupType.Events ? (
                <>
                    <span>{taxonomicGroups.find((g) => g.type === openTab)?.name || openTab}</span>
                    <FlaggedFeature flag="taxonomic-event-sorting" match={true}>
                        <LemonMenu
                            items={[
                                {
                                    label: (
                                        <div className="flex flex-row gap-2">
                                            {eventOrdering === 'name' ? <IconCheck /> : <IconBlank />}
                                            <span>Name</span>
                                        </div>
                                    ),
                                    tooltip: 'Sort events alphabetically',
                                    onClick: () => {
                                        setEventOrdering('name')
                                    },
                                    'data-attr': 'taxonomic-event-sorting-by-name',
                                },
                                {
                                    label: (
                                        <div className="flex flex-row gap-2">
                                            {eventOrdering === '-last_seen_at' ? <IconCheck /> : <IconBlank />}
                                            <span>Recently seen</span>
                                        </div>
                                    ),
                                    tooltip: 'Show the most recent events first',
                                    onClick: () => {
                                        setEventOrdering('-last_seen_at')
                                    },
                                    'data-attr': 'taxonomic-event-sorting-by-recency',
                                },
                                {
                                    label: (
                                        <div className="flex flex-row gap-2">
                                            {!eventOrdering ? <IconCheck /> : <IconBlank />}
                                            <span>Both</span>
                                        </div>
                                    ),
                                    tooltip:
                                        'Sorts events by the day they were last seen, and then by name. The default option.',
                                    onClick: () => {
                                        setEventOrdering(null)
                                    },
                                    'data-attr': 'taxonomic-event-sorting-by-both',
                                },
                            ]}
                        >
                            <LemonButton
                                icon={<IconSort />}
                                size="small"
                                tooltip={`Sorting by ${
                                    eventOrdering === '-last_seen_at'
                                        ? 'recently seen'
                                        : eventOrdering === 'name'
                                        ? 'name'
                                        : 'recently seen and then name'
                                }`}
                            />
                        </LemonMenu>
                    </FlaggedFeature>
                </>
            ) : (
                <>{taxonomicGroups.find((g) => g.type === openTab)?.name || openTab}</>
            )}
        </div>
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
                <div className="taxonomic-group-title">
                    <TaxonomicGroupTitle openTab={openTab} />
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
                        useVerticalLayout ? 'border-r pr-2 mr-2 flex-shrink-0' : 'border-b',
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
