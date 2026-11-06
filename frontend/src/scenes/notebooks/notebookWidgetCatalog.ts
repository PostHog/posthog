import notebookWidgetCatalog from 'products/notebooks/notebook-widget-catalog.json'

import { CustomNotebookNodeAttributes, NotebookNodeProps, PostHogWidgetDefaultView, PostHogWidgetViews } from './types'

export type NotebookWidgetTagName = keyof typeof notebookWidgetCatalog.widgets
export type NotebookWidgetPickerKind =
    | 'action'
    | 'cohort'
    | 'dashboard'
    | 'early-access-feature'
    | 'error-tracking-issue'
    | 'experiment'
    | 'feature-flag'
    | 'group'
    | 'insight'
    | 'llm-trace'
    | 'person'
    | 'recording'
    | 'recording-playlist'
    | 'survey'
    | 'workflow'

type NotebookWidgetViewName<TTagName extends NotebookWidgetTagName> =
    keyof (typeof notebookWidgetCatalog.widgets)[TTagName]['views']

type NotebookWidgetViewComponents<
    TTagName extends NotebookWidgetTagName,
    TAttributes extends CustomNotebookNodeAttributes,
> = {
    [TViewName in NotebookWidgetViewName<TTagName>]: (props: NotebookNodeProps<TAttributes>) => JSX.Element | null
}

export function defineNotebookWidgetViews<
    TAttributes extends CustomNotebookNodeAttributes,
    TTagName extends NotebookWidgetTagName,
>(tagName: TTagName, components: NotebookWidgetViewComponents<TTagName, TAttributes>): PostHogWidgetViews<TAttributes> {
    const definitions = notebookWidgetCatalog.widgets[tagName].views

    return Object.fromEntries(
        Object.entries(definitions).map(([viewName, definition]) => [
            viewName,
            {
                ...definition,
                Component: components[viewName as NotebookWidgetViewName<TTagName>],
            },
        ])
    ) as PostHogWidgetViews<TAttributes>
}

export function getNotebookWidgetDefaultView(tagName: NotebookWidgetTagName): PostHogWidgetDefaultView {
    const defaultView = notebookWidgetCatalog.widgets[tagName].defaultView

    return {
        key: defaultView.name,
        label: defaultView.label,
        description: defaultView.description,
    }
}

export function getNotebookWidgetDefinition(tagName: string):
    | {
          idProp: string
          picker: NotebookWidgetPickerKind
      }
    | undefined {
    const widgets = notebookWidgetCatalog.widgets as Record<
        string,
        { idProp: string; picker: NotebookWidgetPickerKind }
    >
    return widgets[tagName]
}

export { notebookWidgetCatalog }
