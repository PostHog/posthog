import type { LemonMenuItem } from '@posthog/lemon-ui'

import { CreatePostHogWidgetNodeOptions, CustomNotebookNodeAttributes, NotebookNodeAttributes } from './types'

export function getNotebookWidgetViewMenuItem<T extends CustomNotebookNodeAttributes>(
    options: Pick<CreatePostHogWidgetNodeOptions<T>, 'defaultView' | 'views'>,
    attributes: NotebookNodeAttributes<T>,
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<T>>) => void
): LemonMenuItem | null {
    if (!options.defaultView || !options.views) {
        return null
    }

    const selectedView =
        typeof attributes.view === 'string' && options.views[attributes.view]
            ? attributes.view
            : options.defaultView.key
    const setView = (view: string | undefined): void => {
        updateAttributes({ view } as unknown as Partial<NotebookNodeAttributes<T>>)
    }

    return {
        label: 'Change view',
        items: [
            {
                key: options.defaultView.key,
                label: options.defaultView.label,
                tooltip: options.defaultView.description,
                active: selectedView === options.defaultView.key,
                onClick: () => setView(undefined),
            },
            ...Object.entries(options.views).map(([viewKey, view]) => ({
                key: viewKey,
                label: view.label,
                tooltip: view.description,
                active: selectedView === viewKey,
                onClick: () => setView(viewKey),
            })),
        ],
    }
}
