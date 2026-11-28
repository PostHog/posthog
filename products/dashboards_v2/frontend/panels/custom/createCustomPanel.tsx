import { type PanelType, definePanel } from '../core/panelDefinition'
import type { ContentPanel } from '../core/panelSchema'
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
export function createCustomPanel({ packages }: { packages: ContentPackage[] }): PanelType {
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
        ...customSpec(packages),
        addTileOptions: [],
        Component: Custom,
        Loading: CustomLoading,
        menuActions: (actions, context) => {
            const content = contentOf(context.panel)
            const kept = content?.menuActions?.(actions, context) ?? []
            const background = content?.backgroundColor && actions.find((action) => action.key === 'background-color')
            return background && !kept.includes(background) ? [...kept, background] : kept
        },
    })
}
