import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HeatmapsBrowser } from 'scenes/heatmaps/components/HeatmapsBrowser'
import { urls } from 'scenes/urls'

import { ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapScene({ id }: { id: string }): JSX.Element {
    const logic = new heatmapLogic({ id: id })
    const { heatmap, loading } = useValues(logic)

    if (loading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={id === 'new' ? 'New' : heatmap.url}
                description={''}
                resourceType={{
                    type: 'heatmap',
                }}
                forceBackTo={{
                    name: 'Heatmaps',
                    path: urls.heatmaps(),
                    key: 'heatmaps',
                }}
                actions={
                    <LemonButton type="primary" onClick={() => {}} size="small">
                        Save
                    </LemonButton>
                }
            />
            <ScenePanelDivider />
            <HeatmapsBrowser />
        </SceneContent>
    )
}
