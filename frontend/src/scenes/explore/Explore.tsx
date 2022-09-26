import './Explore.scss'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { categories, categorySelectOptions, exploreLogic } from 'scenes/explore/exploreLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { useActions, useValues } from 'kea'
import { LemonSelect } from 'lib/components/LemonSelect'
import { LemonTable } from 'lib/components/LemonTable'
import { ExploreCategory } from '~/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

export const scene: SceneExport = {
    component: Explore,
    logic: exploreLogic,
}

export function Explore(): JSX.Element {
    const { category, rows, rawDataLoading, filters } = useValues(exploreLogic)
    const { setCategory, setFilters } = useActions(exploreLogic)

    return (
        <div className="ExploreScene space-y-2">
            <PageHeader title="Explore" />

            <div className="flex items-center">
                <div className="mr-2">Show me</div>
                <LemonSelect
                    onChange={(e) => setCategory(e as ExploreCategory)}
                    value={category}
                    options={categorySelectOptions}
                    size="small"
                />
                <div className="ml-2 mr-2">where</div>
                <PropertyFilters propertyFilters={filters} onChange={setFilters} pageKey={'explore-filters'} />
            </div>

            <LemonTable
                loading={rawDataLoading}
                columns={
                    rows.length > 0 && Object.keys(rows[0]).length > 0
                        ? Object.keys(rows[0]).map((key) => ({ dataIndex: key, title: key }))
                        : [{ dataIndex: category, title: categories[category] }]
                }
                dataSource={rows}
            />
        </div>
    )
}
