import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { Combobox } from 'lib/ui/Combobox/Combobox'
import { ItemsGridItem, newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

//

export function NewTabScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { itemsGrid } = useValues(newTabSceneLogic({ tabId }))

    return (
        <Combobox
            className="h-[calc(100vh-var(--scene-layout-header-height-with-tabs))] overflow-hidden w-full max-w-full min-w-full flex-1 group/colorful-product-icons colorful-product-icons-true"
            searchSize="lg"
        >
            <div className="sticky top-0 z-10 px-4">
                <div className="p-[2px] border border-[var(--color-bg-fill-highlight-25)] ">
                    <Combobox.Search placeholder="Search for anything..." />
                </div>
            </div>
            <Combobox.Content className="px-4" innerClassName="pt-1 pb-32">
                <Combobox.Empty>Nothing found</Combobox.Empty>

                {itemsGrid.map((item: ItemsGridItem) =>
                    item.types.map((type, typeIndex) => {
                        return (
                            <Combobox.Group
                                key={`${item.category}-${typeIndex}`}
                                value={[type.name, type.filters?.join(' ') ?? '']}
                            >
                                <Combobox.Item asChild>
                                    <Link
                                        to={type.href}
                                        buttonProps={{ variant: 'default', size: 'lg', className: 'w-full capitalize' }}
                                    >
                                        {type.icon}
                                        {type.name}
                                    </Link>
                                </Combobox.Item>
                            </Combobox.Group>
                        )
                    })
                )}
            </Combobox.Content>
        </Combobox>
    )
}
