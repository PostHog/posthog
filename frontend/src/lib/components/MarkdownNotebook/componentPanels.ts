import { NotebookComponentBlockNode, NotebookComponentDefinition, NotebookComponentProps } from './types'

export type ComponentPanel = 'filters' | 'results'

export type ComponentPanelVisibility = Record<ComponentPanel, boolean>

export type ComponentPanelCacheEntry = {
    current?: ComponentPanelVisibility
    remembered?: ComponentPanelVisibility
}

export const DEFAULT_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    filters: false,
    results: true,
}

// Read-only canvases (customer profiles) show results with filters tucked away behind the
// pencil, matching the legacy profile layout.
export const CANVAS_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    filters: false,
    results: true,
}

export const INSERTED_COMPONENT_PANEL_VISIBILITY: ComponentPanelVisibility = {
    filters: false,
    results: true,
}

export function getInsertedComponentPanelVisibility(node: NotebookComponentBlockNode): ComponentPanelVisibility {
    return getComponentPanelVisibility(node, INSERTED_COMPONENT_PANEL_VISIBILITY)
}

export function getComponentPanelVisibility(
    node: NotebookComponentBlockNode,
    fallbackPanels: ComponentPanelVisibility
): ComponentPanelVisibility {
    const legacyViewPanelVisible = typeof node.props.view === 'boolean' ? node.props.view : undefined

    return {
        filters: node.props.showFilters === true,
        results:
            typeof node.props.showResults === 'boolean'
                ? node.props.showResults
                : node.props.hideResults === true
                  ? false
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
        if (
            (key !== 'view' || typeof value !== 'boolean') &&
            key !== 'edit' &&
            key !== 'hideFilters' &&
            key !== 'hideResults' &&
            key !== 'showFilters' &&
            key !== 'showResults'
        ) {
            accumulator[key] = value
        }
        return accumulator
    }, {})

    if (panels.filters) {
        nextProps.showFilters = true
    }
    if (!panels.results) {
        nextProps.hideResults = true
    }

    return nextProps
}
