import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'bi-worksheets'

export function BIWorksheetsSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <BIWorksheetsSceneMenuBarInner /> : null
}

function BIWorksheetsSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-worksheet`,
            label: 'New worksheet',
            icon: <IconPlusSmall />,
            onSelect: () => router.actions.push(`${urls.businessIntelligenceNew()}#q=`),
            pinned: { order: 1, variant: 'primary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
