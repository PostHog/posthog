import { router } from 'kea-router'
import { useCallback } from 'react'

import { Search } from 'lib/components/Search/Search'
import { SearchItem } from 'lib/components/Search/searchLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: NewTabScene,
}

export function NewTabScene(): JSX.Element {
    const handleItemSelect = useCallback((item: SearchItem) => {
        if (item.href) {
            router.actions.push(item.href)
        }
    }, [])

    return (
        <Search.Root
            logicKey="new-tab"
            isActive
            onItemSelect={handleItemSelect}
            showAskAiLink
            className="size-full grow"
        >
            <div className="sticky top-0 w-full max-w-[640px] mx-auto">
                <Search.Input autoFocus className="pt-8" />
                <Search.Status />
            </div>
            <Search.Separator className="-mx-4" />
            <Search.Results
                className="w-full mx-auto grow overflow-y-auto"
                listClassName="max-w-[640px] mx-auto"
                groupLabelClassName="bg-(--scene-layout-background)"
            />
        </Search.Root>
    )
}
