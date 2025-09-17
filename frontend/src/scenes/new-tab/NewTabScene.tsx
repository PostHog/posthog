import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconSearch, IconSidePanel } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox, ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { TabsPrimitive, TabsPrimitiveList, TabsPrimitiveTrigger } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { cn } from 'lib/utils/css-classes'
import { maxLogic } from 'scenes/max/maxLogic'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        'create-new': 'Create new',
        apps: 'Apps',
        'data-management': 'Data management',
    }
    return displayNames[category] || category
}

export function NewTabScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const listboxRef = useRef<ListBoxHandle>(null)
    const { filteredItemsGrid, search, selectedItem, categories, selectedCategory } = useValues(
        newTabSceneLogic({ tabId })
    )
    const { setQuestion, focusInput } = useActions(maxLogic)
    const { setSearch, setSelectedCategory } = useActions(newTabSceneLogic({ tabId }))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    // scroll it to view
    useEffect(() => {
        if (selectedItem) {
            const element = document.querySelector('.selected-new-tab-item')
            element?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
        }
    }, [selectedItem])

    return (
        <ListBox
            ref={listboxRef}
            className="w-full grid grid-rows-[auto_1fr] flex-col h-[calc(100vh-var(--scene-layout-header-height))]"
            virtualFocus
        >
            <div className="flex flex-col gap-4">
                <div className="px-1 @lg/main-content:px-8 pt-2 @lg/main-content:pt-8 mx-auto w-full max-w-[1200px] ">
                    <ListBox.Item asChild virtualFocusIgnore>
                        <LemonInput
                            value={search}
                            onChange={(value) => setSearch(value)}
                            // onKeyDown={handleKeyDown}
                            prefix={<IconSearch />}
                            className="w-full"
                            placeholder="Search..."
                            autoFocus
                            allowClear
                        />
                    </ListBox.Item>
                    <div className="mx-1.5">
                        <div className="flex justify-between items-center relative text-xs font-medium overflow-hidden py-1 px-1.5 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]">
                            <span>
                                <span className="text-tertiary">Try:</span>
                                <ListBox.Item asChild>
                                    <ButtonPrimitive
                                        size="xxs"
                                        className="text-xs"
                                        onClick={() => setSearch('New SQL query')}
                                    >
                                        New SQL query
                                    </ButtonPrimitive>
                                </ListBox.Item>
                                <span className="text-tertiary">or</span>
                                <ListBox.Item asChild>
                                    <ButtonPrimitive
                                        size="xxs"
                                        className="text-xs"
                                        onClick={() => setSearch('Experiment')}
                                    >
                                        Experiment
                                    </ButtonPrimitive>
                                </ListBox.Item>
                            </span>
                            <span className="text-primary flex gap-1 items-center">
                                <ListBox.Item asChild>
                                    <ButtonPrimitive
                                        size="xxs"
                                        onClick={() => {
                                            openSidePanel(SidePanelTab.Max)
                                            setSearch('')
                                            setQuestion(search)
                                            focusInput()
                                        }}
                                        className="text-xs"
                                    >
                                        Ask Max!
                                        <IconSidePanel />
                                    </ButtonPrimitive>
                                </ListBox.Item>
                            </span>
                        </div>
                    </div>
                </div>
                <TabsPrimitive value={selectedCategory} onValueChange={setSelectedCategory}>
                    <TabsPrimitiveList className="border-b">
                        <div className="max-w-[1200px] mx-auto w-full px-1 @lg/main-content:px-8 flex">
                            {categories.map((category) => (
                                <TabsPrimitiveTrigger
                                    value={category.key}
                                    className="px-2 py-1 cursor-pointer"
                                    key={category.key}
                                >
                                    {category.label}
                                </TabsPrimitiveTrigger>
                            ))}
                        </div>
                    </TabsPrimitiveList>
                </TabsPrimitive>
            </div>

            <ScrollableShadows
                direction="vertical"
                className="flex flex-col gap-4 overflow-auto h-full"
                innerClassName="pt-6"
            >
                <div className="flex flex-col flex-1 max-w-[1200px] mx-auto w-full gap-4 px-3 @lg/main-content:px-8">
                    {filteredItemsGrid.length === 0 ? (
                        <div className="flex flex-col gap-4">
                            <div className="flex gap-1 items-center">
                                No results found,{' '}
                                <ListBox.Item asChild>
                                    <LemonButton type="primary" size="xsmall" onClick={() => setSearch('')}>
                                        Clear search
                                    </LemonButton>{' '}
                                </ListBox.Item>
                                or{' '}
                                <ListBox.Item asChild>
                                    <LemonButton
                                        type="primary"
                                        size="xsmall"
                                        onClick={() => openSidePanel(SidePanelTab.Max)}
                                    >
                                        Ask Max!
                                    </LemonButton>
                                </ListBox.Item>
                            </div>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 @sm/main-content:grid-cols-2 @md/main-content:grid-cols-3 gap-4 group/colorful-product-icons colorful-product-icons-true">
                            {filteredItemsGrid.map(({ category, types }) => (
                                <div className="mb-8" key={category}>
                                    <div className="mb-4">
                                        <h3 className="text-lg font-medium text-muted">
                                            {search ? (
                                                <SearchHighlightMultiple
                                                    string={getCategoryDisplayName(category)}
                                                    substring={search}
                                                />
                                            ) : (
                                                getCategoryDisplayName(category)
                                            )}
                                        </h3>
                                    </div>
                                    <div className="flex flex-col gap-2">
                                        {types.map((qt, index) => (
                                            <ListBox.Item asChild focusFirst={index === 0}>
                                                <Link
                                                    key={qt.name}
                                                    to={qt.href}
                                                    className={cn('w-full @sm/main-content:w-auto')}
                                                    buttonProps={{
                                                        size: 'base',
                                                    }}
                                                >
                                                    <span className="text-sm">{qt.icon ?? qt.name[0]}</span>
                                                    <span className="text-sm truncate text-primary">
                                                        {search ? (
                                                            <SearchHighlightMultiple
                                                                string={qt.name}
                                                                substring={search}
                                                            />
                                                        ) : (
                                                            qt.name
                                                        )}
                                                    </span>
                                                </Link>
                                            </ListBox.Item>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </ScrollableShadows>
        </ListBox>
    )
}
