import { useMemo } from 'react'

import { SidebarProductMeta } from '~/layout/panel-layout/sidebarProductMeta'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'

import { TodayPeopleRow } from './todayPeopleLogic'
import { TODAY_PEOPLE_GROUP_ICON, TODAY_PEOPLE_ROWS, todayPeopleRowIcon } from './todayPeopleRows'
import { TodayExplainerPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

// Group type names belong to each project, so the copy can only say what a group type is, in the project's own words.
function groupExplainer(label: string): SidebarProductMeta {
    const plural = label.toLowerCase()
    return {
        description: `Your project tracks ${plural} as a group type. Each one collects its own events, properties, and people, so you can look at usage above the level of a single person.`,
        example: `Find the ${plural} with the most activity this month.`,
        docsHref: 'https://posthog.com/docs/product-analytics/group-analytics',
    }
}

export function TodayPeopleNavRow({
    row,
    meta,
    active,
}: {
    row: TodayPeopleRow
    meta?: string
    active: boolean
}): JSX.Element {
    const icon = row.kind === 'static' ? todayPeopleRowIcon(row.key) : TODAY_PEOPLE_GROUP_ICON
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({
            kind: 'explainer',
            label: row.label,
            icon,
            ...(row.kind === 'static' ? TODAY_PEOPLE_ROWS[row.key].explainer : groupExplainer(row.label)),
        }),
        [row.kind, row.key, row.label, icon]
    )
    return (
        <TodayPreviewTrigger payload={preview}>
            <SidebarRow
                value={`browse:${row.key}`}
                label={row.label}
                meta={meta}
                icon={icon}
                to={row.href}
                active={active}
                dataAttr={`people-sidebar-${row.key}`}
            />
        </TodayPreviewTrigger>
    )
}
