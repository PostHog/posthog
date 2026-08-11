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

    const defaultView = options.defaultView
    const selectedView =
        typeof attributes.view === 'string' && options.views[attributes.view] ? attributes.view : defaultView.key
    const setView = (view: string): void => {
        updateAttributes({ view } as unknown as Partial<NotebookNodeAttributes<T>>)
    }

    return {
        label: 'Change view',
        closeOnClickInside: false,
        closeParentPopoverOnClickInside: false,
        items: [
            {
                key: defaultView.key,
                label: defaultView.label,
                tooltip: defaultView.description,
                active: selectedView === defaultView.key,
                onClick: () => setView(defaultView.key),
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
