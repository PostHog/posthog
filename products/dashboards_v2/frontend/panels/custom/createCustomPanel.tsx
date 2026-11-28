import { type PanelType, definePanel } from '../core/panelDefinition'
import type { ContentPanel } from '../core/panelSchema'
import type { TileCustomization } from '../core/panelSpec'
import { PanelLoading } from '../core/PanelView'
import {
    type ContentPackage,
    type CustomConfig,
    type CustomContent,
    contentProps,
    contentsByName,
    customSpec,
} from './customSpec'

// The content is the owning team's own UI, so people get no menu entries or customizations unless that team opts in.
// No "add tile" entry either: the team's code decides where its contents go.
export function createCustomPanel({
    packages,
    allowedCustomizations = [],
}: {
    packages: ContentPackage[]
    allowedCustomizations?: TileCustomization[]
}): PanelType {
    const contents = contentsByName(packages)
    const contentOf = (panel: ContentPanel<CustomConfig>): CustomContent | undefined =>
        contents.get(panel.config.content)
    function Custom({ panel }: { panel: ContentPanel<CustomConfig> }): JSX.Element | null {
        const content = contentOf(panel)
        const props = content && contentProps(content, panel.config)
        return content && props ? <content.Component {...props} /> : null
    }
    function CustomLoading({ panel }: { panel: ContentPanel<CustomConfig> }): JSX.Element {
        const content = contentOf(panel)
        const props = content && contentProps(content, panel.config)
        return content?.Loading && props ? <content.Loading {...props} /> : <PanelLoading />
    }
    return definePanel<CustomConfig, 'custom'>({
        ...customSpec(packages, allowedCustomizations),
        addTileOptions: [],
        Component: Custom,
        Loading: CustomLoading,
        menuActions: (actions, context) => contentOf(context.panel)?.menuActions?.(actions, context) ?? [],
    })
}
