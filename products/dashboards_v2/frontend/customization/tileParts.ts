import type { ContentWidget } from '../layout/dashboardTypes'

export interface ContentWidgetParts {
    header?: boolean
    description?: boolean
    footer?: boolean
}

/** The widget types whose tiles have a footer. `WidgetFooter` holds what each one renders there. */
export const FOOTER_WIDGET_TYPES = ['stat', 'line', 'bar'] as const satisfies readonly ContentWidget['type'][]

export type FooterWidgetType = (typeof FOOTER_WIDGET_TYPES)[number]

export function isFooterWidgetType(type: ContentWidget['type']): type is FooterWidgetType {
    return FOOTER_WIDGET_TYPES.some((footerType) => footerType === type)
}

/** Whether a content tile has anything to put in a part. The description renders inside the header, so it needs a title. */
export function hasPart(widget: ContentWidget, part: keyof ContentWidgetParts): boolean {
    switch (part) {
        case 'header':
            return !!widget.title
        case 'description':
            return !!widget.title && !!widget.description
        case 'footer':
            return isFooterWidgetType(widget.type)
    }
}

/** The description lives in the header, so hiding the header hides it too. */
export function showsPart(widget: ContentWidget, part: keyof ContentWidgetParts): boolean {
    if (part === 'description' && widget.parts?.header === false) {
        return false
    }
    return widget.parts?.[part] !== false
}

export function isPartShown(widget: ContentWidget, part: keyof ContentWidgetParts): boolean {
    return hasPart(widget, part) && showsPart(widget, part)
}
