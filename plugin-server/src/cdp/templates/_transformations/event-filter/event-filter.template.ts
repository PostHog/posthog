import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-event-filter',
    name: 'Event Filter',
    description:
        'Filters out events based on property values and event names. Configure filters in the UI to determine which events to drop.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// This transformation is special - it doesn't actually transform the event
// The filtering is handled by the filter infrastructure before this code runs
// If this code runs, it means the event passed all filters and should be kept

// Simply return the event as-is
return event
    `,
    inputs_schema: [],
    uses_filter_infrastructure: true
} 