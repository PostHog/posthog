import { IconPencil, IconRewindPlay, IconTrash } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { FilterLogicalOperator, RecordingUniversalFilters, ReplayTabs } from '~/types'

const RESOURCE_TYPE = 'definition'

export function eventRecordingFilters(eventName: string): Partial<RecordingUniversalFilters> {
    return {
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [{ id: eventName, type: 'events', order: 0, name: eventName }],
                },
            ],
        },
    }
}

interface DefinitionViewSceneMenuBarProps {
    eventName: string
    isEvent: boolean
    isVirtual: boolean
    openEditDefinition: () => void
    openDeleteDialog: () => void
}

export function DefinitionViewSceneMenuBar(props: DefinitionViewSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <DefinitionViewSceneMenuBarInner {...props} /> : null
}

function DefinitionViewSceneMenuBarInner({
    eventName,
    isEvent,
    isVirtual,
    openEditDefinition,
    openDeleteDialog,
}: DefinitionViewSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        ...(!isVirtual
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-edit`,
                      label: 'Edit',
                      icon: <IconPencil />,
                      onSelect: openEditDefinition,
                      pinned: { order: 1, variant: 'primary', dataAttr: 'edit-definition' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isEvent
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-view-recordings`,
                      label: 'View recordings',
                      icon: <IconRewindPlay />,
                      onSelect: () => newInternalTab(urls.replay(ReplayTabs.Home, eventRecordingFilters(eventName))),
                      pinned: { order: 2, variant: 'secondary', dataAttr: 'event-definition-view-recordings' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!isVirtual
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete',
                      icon: <IconTrash />,
                      destructive: true,
                      tooltip: 'Delete this definition. Associated data will remain.',
                      onSelect: openDeleteDialog,
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
