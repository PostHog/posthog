import type { ContentWidget } from '../layout/dashboardTypes'

export const NEW_TILES: { label: string; widget: ContentWidget }[] = [
    {
        label: 'Number',
        widget: { type: 'stat', title: 'New number', query: { kind: 'hogql', sql: 'select count() as total' } },
    },
    {
        label: 'Line chart',
        widget: {
            type: 'line',
            title: 'New line chart',
            query: { kind: 'hogql', sql: 'select count() from events by day' },
        },
    },
    {
        label: 'Bar chart',
        widget: {
            type: 'bar',
            title: 'New bar chart',
            query: { kind: 'hogql', sql: 'select count() from events by country' },
        },
    },
    { label: 'Text', widget: { type: 'markdown', text: 'Write notes in **Markdown**.' } },
]
