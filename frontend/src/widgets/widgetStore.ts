import { Node } from '~/queries/schema/schema-general'

import { MountQueryEditorOptions } from './types'

export interface WidgetInstanceState {
    query: Node | Record<string, any>
    onQueryChange?: (query: Node) => void
    theme: 'light' | 'dark'
    onClose?: () => void
}

/** Tiny external store so `handle.update(props)` re-renders without recreating the React root. */
export class WidgetInstanceStore {
    private state: WidgetInstanceState
    private listeners = new Set<() => void>()

    constructor(options: MountQueryEditorOptions) {
        this.state = {
            query: options.query,
            onQueryChange: options.onQueryChange,
            theme: options.theme ?? 'light',
            onClose: options.onClose,
        }
    }

    get = (): WidgetInstanceState => this.state

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
    }

    setQuery(query: Node): void {
        // The Query component is controlled (we pass setQuery), so edits must flow
        // back down through a re-render with the new query prop.
        this.update({ query })
    }

    update(partial: Partial<WidgetInstanceState>): void {
        this.state = { ...this.state, ...partial }
        for (const listener of this.listeners) {
            listener()
        }
    }
}
