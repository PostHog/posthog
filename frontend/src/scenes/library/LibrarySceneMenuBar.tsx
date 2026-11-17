import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { navigateToHref } from 'lib/utils/navigateToHref'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { libraryLogic } from './libraryLogic'

const RESOURCE_TYPE = 'library'

export function LibrarySceneMenuBar({ objectType }: { objectType?: string }): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <LibrarySceneMenuBarInner objectType={objectType} />
}

function LibrarySceneMenuBarInner({ objectType }: { objectType?: string }): JSX.Element {
    const { createItemsByType, objectTypeByValue } = useValues(libraryLogic)
    const items = objectType ? (createItemsByType[objectType] ?? []) : []
    const typeLabel = objectType ? (objectTypeByValue[objectType]?.label.toLowerCase() ?? 'object') : 'object'
    const newLabel = `New ${typeLabel}`
    const pinned = { order: 0, variant: 'primary', dataAttr: 'library-new-object' } as const

    const actions: SceneAction[] = [
        ...(items.length === 1
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      id: `${RESOURCE_TYPE}-menubar-new-object`,
                      label: newLabel,
                      icon: <IconPlus />,
                      onSelect: () => navigateToHref(items[0].href),
                      pinned,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(items.length > 1
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-new-object`,
                      label: newLabel,
                      icon: <IconPlus />,
                      items: items.map((item) => ({
                          id: `${RESOURCE_TYPE}-menubar-new-object-${item.path}`,
                          dataAttr: 'library-new-object',
                          label: item.path.split('/').pop() ?? item.path,
                          onSelect: () => navigateToHref(item.href),
                      })),
                      pinned,
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
