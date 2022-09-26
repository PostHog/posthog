import './Explore.scss'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { exploreLogic } from 'scenes/explore/exploreLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/components/LemonButton'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: Explore,
    logic: exploreLogic,
}

export function Explore(): JSX.Element {
    return (
        <div className="ExploreScene">
            <PageHeader
                title="Explore"
                buttons={
                    <LemonButton type="primary" to={urls.explore()} data-attr="new-explore-query">
                        New Query
                    </LemonButton>
                }
            />
        </div>
    )
}
