import React from 'react'
import { SceneExport } from '../sceneTypes'
import { urls } from '../urls'

export const scene: SceneExport = {
    component: Taxonomy,
    logic: undefined,
    paramsToProps: ({ params: { fixedFilters } }) => ({ fixedFilters, key: 'Taxonomy', sceneUrl: urls.taxonomy() }),
}

export function Taxonomy(): JSX.Element {
    return <div>Taxonomy</div>
}
