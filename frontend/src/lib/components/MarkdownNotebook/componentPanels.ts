import { NotebookComponentBlockNode, NotebookComponentDefinition, NotebookComponentProps } from './types'

export type ComponentPanel = 'filters' | 'results'

export type ComponentPanelVisibility = Record<ComponentPanel, boolean>

export type ComponentPanelCacheEntry = {
    current?: ComponentPanelVisibility
    remembered?: ComponentPanelVisibility
}

export const DEFAULT_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    filters: true,
    results: true,
}

export const INSERTED_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    filters: true,
    results: true,
}

export const INSERTED_QUERY_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    filters: false,
    results: true,
}

export function getInsertedComponentPanelVisibility(node: NotebookComponentBlockNode): ComponentPanelVisibility {
    return getComponentPanelVisibility(
        node,
        node.tagName === 'Query' ? INSERTED_QUERY_COMPONENT_PANEL_VISIBILITY : INSERTED_COMPONENT_PANEL_VISIBILITY
    )
}

export function getComponentPanelVisibility(
    node: NotebookComponentBlockNode,
    fallbackPanels: ComponentPanelVisibility
): ComponentPanelVisibility {
    const legacyViewPanelVisible = typeof node.props.view === 'boolean' ? node.props.view : undefined
    const legacyEditPanelVisible = typeof node.props.edit === 'boolean' ? node.props.edit : undefined

    return {
        filters:
            typeof node.props.hideFilters === 'boolean'
                ? !node.props.hideFilters
                : (legacyEditPanelVisible ?? fallbackPanels.filters),
        results:
            typeof node.props.hideResults === 'boolean'
                ? !node.props.hideResults
                : (legacyViewPanelVisible ?? fallbackPanels.results),
    }
}

export function shouldPersistComponentPanelProps(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null | undefined
): boolean {
    return !!definition && node.tagName !== 'Prompt' && !definition.hideModeActions
}

export function withPersistedComponentPanelProps(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null | undefined,
    panels: ComponentPanelVisibility
): NotebookComponentBlockNode {
    if (!shouldPersistComponentPanelProps(node, definition)) {
        return node
    }

    return {
        ...node,
        props: getComponentPropsWithPanelVisibility(node.props, panels),
    }
}

export function getComponentPropsWithPanelVisibility(
    props: NotebookComponentProps,
    panels: ComponentPanelVisibility
): NotebookComponentProps {
    const nextProps = Object.entries(props).reduce<NotebookComponentProps>((accumulator, [key, value]) => {
        if (key !== 'view' && key !== 'edit' && key !== 'hideFilters' && key !== 'hideResults') {
            accumulator[key] = value
        }
        return accumulator
    }, {})

    if (!panels.filters) {
        nextProps.hideFilters = true
    }
    if (!panels.results) {
        nextProps.hideResults = true
    }

    return nextProps
}
