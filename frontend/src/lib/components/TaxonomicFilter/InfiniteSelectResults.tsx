import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { InfiniteList } from 'lib/components/TaxonomicFilter/InfiniteList'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'

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
    const { totalResultCount, totalListCount } = useValues(logic)

    const group = taxonomicGroups.find((g) => g.type === groupType)

    // :TRICKY: use `totalListCount` (results + extra) to toggle interactivity, while showing `totalResultCount`
    const canInteract = totalListCount > 0

    return (
        <LemonTag
            type={isActive ? 'primary' : canInteract ? 'option' : 'muted'}
            data-attr={`taxonomic-tab-${groupType}`}
            onClick={canInteract ? onClick : undefined}
            weight="normal"
        >
            {group?.render ? (
                group?.name
            ) : (
                <>
                    {group?.name}
                    {': '}
                    {totalResultCount ?? '...'}
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
    const { setActiveTab, selectItem } = useActions(taxonomicFilterLogic)
    const RenderComponent = activeTaxonomicGroup?.render

    const listComponent = RenderComponent ? (
        <RenderComponent
            {...(activeTaxonomicGroup?.componentProps ?? {})}
            value={value}
            onChange={(newValue) => selectItem(activeTaxonomicGroup, newValue, newValue)}
        />
    ) : (
        <InfiniteList popupAnchorElement={popupAnchorElement} />
    )

    if (taxonomicGroupTypes.length === 1) {
        return (
            <BindLogic
                logic={infiniteListLogic}
                props={{ ...taxonomicFilterLogicProps, listGroupType: taxonomicGroupTypes[0] }}
            >
                {listComponent}
            </BindLogic>
        )
    }

    const openTab = activeTab || taxonomicGroups[0].type
    return (
        <>
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
            <div className="taxonomic-group-title with-border">
                {taxonomicGroups.find((g) => g.type === openTab)?.name || openTab}
            </div>
            {taxonomicGroupTypes.map((groupType) => {
                return (
                    <div key={groupType} className={clsx('mt-2', groupType === openTab ? 'block' : 'hidden')}>
                        <BindLogic
                            logic={infiniteListLogic}
                            props={{ ...taxonomicFilterLogicProps, listGroupType: groupType }}
                        >
                            {listComponent}
                        </BindLogic>
                    </div>
                )
            })}
        </>
    )
}
