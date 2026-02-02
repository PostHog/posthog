import { router } from 'kea-router'
import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import { Search } from 'lib/components/Search/Search'
import { SearchItem } from 'lib/components/Search/searchLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: NewTabScene,
}

export function NewTabScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const initialSearchValue = useMemo(() => {
        const q = searchParams?.q
        return typeof q === 'string' ? q : ''
    }, []) // Only compute on mount

    const debounceRef = useRef<number>()

    useEffect(() => {
        return () => {
            if (debounceRef.current) {
                clearTimeout(debounceRef.current)
            }
        }
    }, [])

    const handleSearchValueChange = useCallback((value: string) => {
        if (debounceRef.current) {
            clearTimeout(debounceRef.current)
        }
        debounceRef.current = window.setTimeout(() => {
            const newSearchParams = value ? { q: value } : {}
            router.actions.push(urls.newTab(), undefined, newSearchParams)
        }, 300)
    }, [])

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
            initialSearchValue={initialSearchValue}
            onSearchValueChange={handleSearchValueChange}
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
