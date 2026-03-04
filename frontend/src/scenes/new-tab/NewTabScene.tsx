import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback } from 'react'

import { Search } from 'lib/components/Search/Search'
import { SearchItem } from 'lib/components/Search/searchLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { newTabPreferencesLogic } from './newTabPreferencesLogic'

export const scene: SceneExport = {
    component: NewTabScene,
}

export function NewTabScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const isAIFirst = useFeatureFlag('AI_FIRST')
    const { aiFirstSearchEnabled } = useValues(newTabPreferencesLogic)
    const { setAiFirstSearchEnabled } = useActions(newTabPreferencesLogic)
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
            className="size-full grow"
            suggestedItems={suggestedItems}
        >
            <div className="sticky top-0 w-full max-w-[640px] mx-auto">
                {isAIFirst && (
                    <div className="flex items-center justify-end pt-4 px-2">
                        <LemonSwitch
                            checked={aiFirstSearchEnabled}
                            onChange={setAiFirstSearchEnabled}
                            label="AI-first"
                            size="small"
                        />
                    </div>
                )}
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
