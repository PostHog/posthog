import type { ReactNode } from 'react'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export const WIDGET_SETTINGS_FORM_GRID_CLASS = 'grid grid-cols-1 sm:grid-cols-2 gap-4'

export const WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS = 'sm:col-span-2'

export function WidgetSettingsModalSections({ children }: { children: ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-4">{children}</div>
}

export function WidgetSettingsModalDivider(): JSX.Element {
    return <LemonDivider className="my-0" />
}

export type WidgetSettingsModalSectionProps = {
    title: string
    children: ReactNode
}

export function WidgetSettingsModalSection({ title, children }: WidgetSettingsModalSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <h5 className="text-sm font-semibold m-0">{title}</h5>
            <div className={WIDGET_SETTINGS_FORM_GRID_CLASS}>{children}</div>
        </section>
    )
}
