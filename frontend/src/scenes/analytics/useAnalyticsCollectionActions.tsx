import { useActions, useValues } from 'kea'

import { IconFolderMove, IconMinusSmall, IconPlusSmall } from '@posthog/icons'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'

import { ShareToSpaceTarget, analyticsShareLogic, shareTargetKey } from './analyticsShareLogic'

/**
 * The collection actions: add when the item is in no collection, else move or remove. Empty without a target. The
 * scene mounts `AnalyticsCollectionDialogHost` for the same target, which opens the dialog and loads the item's
 * collection.
 */
export function useAnalyticsCollectionActions(
    target: ShareToSpaceTarget | null,
    dataAttrKey: string,
    { group = 'file', section = 'project-tree' }: { group?: SceneActionGroup; section?: string } = {}
): SceneAction[] {
    const { itemSpaces, sharing } = useValues(analyticsShareLogic)
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    if (!target) {
        return []
    }
    const space = itemSpaces[shareTargetKey(target)]
    const open = (): void => openShareToSpace(target)

    // While the lookup is unknown, or after it failed, one neutral item opens the dialog, which loads the item itself.
    if (space === undefined || space === null) {
        const adding = space === null
        return [
            {
                group,
                section,
                id: adding ? `${dataAttrKey}-menubar-add-to-collection` : `${dataAttrKey}-menubar-move-to-collection`,
                label: adding ? 'Add to collection' : 'Move to collection',
                icon: adding ? <IconPlusSmall /> : <IconFolderMove />,
                opensFloatingUi: true,
                onSelect: open,
            },
        ]
    }
    return [
        {
            group,
            section,
            id: `${dataAttrKey}-menubar-move-to-collection`,
            label: 'Move to another collection',
            icon: <IconFolderMove />,
            opensFloatingUi: true,
            onSelect: open,
        },
        {
            group,
            section,
            id: `${dataAttrKey}-menubar-remove-from-collection`,
            label: `Remove from ${space}`,
            icon: <IconMinusSmall />,
            disabledReason: sharing ? 'Saving' : undefined,
            onSelect: () => moveItem(target, null),
        },
    ]
}
