import { useActions, useValues } from 'kea'

import { IconSearch, IconWrench } from '@posthog/icons'
import {
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Item,
    ItemContent,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { toolsLogic } from './toolsLogic'
import { toolLabel } from './toolsUtils'

export const scene: SceneExport = {
    component: Tools,
    logic: toolsLogic,
}

export function Tools(): JSX.Element {
    const { toolGroups: groups, search } = useValues(toolsLogic)
    const { setSearch } = useActions(toolsLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Tools"
                description="Working pages for querying, building and running your product."
                resourceType={{ type: 'tools', forceIcon: <IconWrench /> }}
            />
            <div
                data-quill
                className="@container/tools flex flex-col gap-4 group/colorful-product-icons colorful-product-icons-true"
            >
                <InputGroup className="max-w-120">
                    <InputGroupAddon>
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        aria-label="Search tools"
                        placeholder="Search tools"
                        value={search}
                        onChange={(event: React.ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                        data-attr="tools-search"
                    />
                </InputGroup>
                {!groups.length ? (
                    <Text size="sm" variant="muted">
                        No tools match that search.
                    </Text>
                ) : (
                    groups.map((group) => (
                        <section key={group.category} className="flex flex-col gap-2">
                            <Text size="xs" weight="medium" variant="muted" render={<h2 />} className="m-0">
                                {group.category}
                            </Text>
                            <ItemGroup className="grid gap-2 @xl/tools:grid-cols-2 @4xl/tools:grid-cols-3">
                                {group.tools.map((tool) => (
                                    <Item
                                        key={tool.href}
                                        variant="outline"
                                        size="sm"
                                        // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
                                        className="text-foreground hover:bg-fill-hover hover:text-foreground"
                                        render={<LinkPrimitive to={tool.href ?? ''} data-attr="tools-page-tool" />}
                                    >
                                        <ItemMedia variant="icon" aria-hidden>
                                            {iconForType(
                                                (tool.iconType ?? tool.type) as FileSystemIconType,
                                                tool.iconColor
                                            )}
                                        </ItemMedia>
                                        <ItemContent className="min-w-0">
                                            <ItemTitle className="truncate">{toolLabel(tool)}</ItemTitle>
                                        </ItemContent>
                                    </Item>
                                ))}
                            </ItemGroup>
                        </section>
                    ))
                )}
            </div>
        </SceneContent>
    )
}
