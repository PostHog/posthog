import { useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback } from 'react'

import { Search } from 'lib/components/Search/Search'
import { SearchItem } from 'lib/components/Search/searchLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { HomeViewToggle } from '~/layout/scenes/HomeViewToggle'

export const scene: SceneExport = {
    component: NewTabScene,
}

export function NewTabScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const handleItemSelect = useCallback((item: SearchItem) => {
        if (item.href) {
            router.actions.push(item.href)
        }
    }, [])

    const suggestedItems: SearchItem[] =
        searchParams.source === 'sql_editor'
            ? [
                  {
                      id: 'suggested-sql-editor',
                      name: 'SQL editor',
                      displayName: 'SQL editor',
                      category: 'suggested',
                      href: urls.sqlEditor(),
                      itemType: 'sql_editor',
                  },
              ]
            : []

    return (
        <Search.Root
            logicKey="new-tab"
            isActive
            onItemSelect={handleItemSelect}
            showAskAiLink
            className="size-full grow relative"
            suggestedItems={suggestedItems}
        >
            <HomeViewToggle current="search" />
            <div className="sticky top-0 w-full max-w-[640px] mx-auto">
                {/* Extra top padding keeps the input clear of the home view picker */}
                <Search.Input autoFocus className="pt-14" />
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
