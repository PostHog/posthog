import { useActions, useValues } from 'kea'

import { IconFolderMove, IconMinusSmall, IconPlusSmall } from '@posthog/icons'

import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'

import { ShareToSpaceTarget, analyticsShareLogic, shareTargetKey } from './analyticsShareLogic'

/**
 * The File menu's collection actions: add when the item is in no collection, else move or remove.
 * The scene mounts `AnalyticsCollectionDialogHost` for the same target, which opens the dialog and loads the
 * item's collection.
 */
export function AnalyticsCollectionMenuBarItems({
    target,
    dataAttrKey,
}: {
    target: ShareToSpaceTarget
    dataAttrKey: string
}): JSX.Element {
    const { itemSpaces, sharing } = useValues(analyticsShareLogic)
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    const space = itemSpaces[shareTargetKey(target)]

    // While the lookup is unknown, or after it failed, one neutral item opens the dialog, which loads the item itself.
    if (space === undefined) {
        return (
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => openShareToSpace(target)}
                data-attr={`${dataAttrKey}-menubar-move-to-collection`}
            >
                <IconFolderMove />
                Move to collection
            </SceneMenuBarItem>
        )
    }
    if (space === null) {
        return (
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => openShareToSpace(target)}
                data-attr={`${dataAttrKey}-menubar-add-to-collection`}
            >
                <IconPlusSmall />
                Add to collection
            </SceneMenuBarItem>
        )
    }
    return (
        <>
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => openShareToSpace(target)}
                data-attr={`${dataAttrKey}-menubar-move-to-collection`}
            >
                <IconFolderMove />
                Move to another collection
            </SceneMenuBarItem>
            <SceneMenuBarItem
                onClick={() => moveItem(target, null)}
                disabled={sharing}
                data-attr={`${dataAttrKey}-menubar-remove-from-collection`}
            >
                <IconMinusSmall />
                Remove from {space}
            </SceneMenuBarItem>
        </>
    )
}
