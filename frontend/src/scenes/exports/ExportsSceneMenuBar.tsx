import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'exports'

export function ExportsSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ExportsSceneMenuBarInner /> : null
}

function ExportsSceneMenuBarInner(): JSX.Element {
    const { exportsLoading } = useValues(exportsLogic)
    const { loadExports } = useActions(exportsLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-refresh`,
            label: 'Refresh',
            icon: <IconRefresh />,
            disabledReason: exportsLoading ? 'Loading exports' : undefined,
            onSelect: loadExports,
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <Button onClick={loadExports} variant="primary" loading={exportsLoading} data-attr="export-refresh">
                        <IconRefresh />
                        Refresh
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
