import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { newViewLogic } from './newViewLogic'
import { VIEW_TYPES } from './viewsUtils'
import { ViewTypeIcon } from './ViewTypeIcon'

export const scene: SceneExport = {
    component: NewView,
}

export function NewView(): JSX.Element {
    const { pickNewViewType } = useActions(newViewLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="New view"
                description="Pick what to create."
                resourceType={{ type: 'views', forceIcon: <IconPlus /> }}
            />
            <ItemGroup data-quill className="max-w-160 gap-2">
                {VIEW_TYPES.map((info) => (
                    <Item
                        key={info.type}
                        variant="outline"
                        render={<button type="button" />}
                        className="text-start text-foreground hover:bg-fill-hover"
                        onClick={() => pickNewViewType(info.type)}
                        data-attr={`views-new-page-${info.type}`}
                    >
                        <ItemMedia variant="icon" aria-hidden>
                            <ViewTypeIcon type={info.type} />
                        </ItemMedia>
                        <ItemContent>
                            <ItemTitle>{info.label}</ItemTitle>
                            <ItemDescription>{info.description}</ItemDescription>
                        </ItemContent>
                    </Item>
                ))}
            </ItemGroup>
        </SceneContent>
    )
}
