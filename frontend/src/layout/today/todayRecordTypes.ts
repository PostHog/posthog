import { fileSystemTypes } from '~/products'
import type { FileSystemIconType } from '~/queries/schema/schema-general'

import type { TodayRecentTypeCopy } from './todayRecents'

export interface TodayRecordType extends TodayRecentTypeCopy {
    /** The pane rows' icon. A pane with icons of its own, such as People, leaves it out. */
    iconType?: FileSystemIconType
}

// pinned: stored as the `type` of every pinned self-driving inbox report. Renaming it orphans those pins.
export const TODAY_REPORT_RECORD_TYPE = 'signal_report'

const WORKFLOW: TodayRecordType = {
    iconType: 'workflows',
    label: 'Workflow',
    description: 'A workflow. Open it to see its steps, runs, and metrics.',
}

const TODAY_RECORD_TYPES: Record<string, TodayRecordType> = {
    person: {
        label: 'Person',
        description: 'A person in your project. Open their page to see their properties, events, and recordings.',
    },
    group: { label: 'Group', description: 'A group in your project. Open it to see its properties and activity.' },
    cohort: {
        label: 'Cohort',
        description: 'A cohort in your project. Open it to see who belongs to it and how it is defined.',
    },
    account: {
        label: 'Account',
        description: 'A customer account. Open it to see its activity, notes, and related users.',
    },
    ticket: { label: 'Ticket', description: 'A support ticket. Open it to read the conversation and reply.' },
    canvas: { label: 'Canvas', description: 'A canvas. Open it to see the page built from your data.' },
    dashboard: { label: 'Dashboard', description: 'A dashboard. Open it to see its insights and widgets.' },
    insight: { label: 'Insight', description: 'An insight. Open it to see its chart and the query behind it.' },
    notebook: { label: 'Notebook', description: 'A notebook. Open it to read its analysis.' },
    collection: { label: 'Collection', description: 'A collection. Open it to see the analytics kept in it.' },
    error_tracking_issue: {
        iconType: 'error_tracking',
        label: 'Issue',
        description: 'An error tracking issue. Open it to see its stack trace, events, and affected users.',
    },
    logs_view: {
        iconType: 'logs',
        label: 'Logs view',
        description: 'A saved logs view. Open it to see the logs that match its filters.',
    },
    trace: {
        iconType: 'tracing',
        label: 'Trace',
        description: 'A trace. Open it to see its spans, timings, and errors.',
    },
    feature_flag: {
        label: 'Feature flag',
        description: 'A feature flag. Open it to see who gets it, its rollout, and its usage.',
    },
    experiment: {
        label: 'Experiment',
        description: 'An experiment. Open it to see its variants, metrics, and results.',
    },
    early_access_feature: {
        label: 'Early access feature',
        description: 'An early access feature. Open it to see its stage and who has opted in.',
    },
    // Automate. The file system calls a workflow `workflows`, and the Automate pane calls it `workflow`.
    workflow: WORKFLOW,
    workflows: WORKFLOW,
    'hog_function/destination': {
        iconType: 'data_pipeline',
        label: 'Destination',
        description: 'A destination. Open it to see its configuration and the events it sent.',
    },
    subscription: {
        iconType: 'team_activity',
        label: 'Subscription',
        description: 'A subscription. Open it to see its schedule and delivery history.',
    },
    scout: {
        iconType: 'inbox',
        label: 'Scout',
        description: 'A scout. Open it to see its runs, reports, and what it has learned.',
    },
    event_definition: {
        iconType: 'event_definition',
        label: 'Event',
        description: 'An event definition. Open it to see its description, properties, and where it is used.',
    },
    property_definition: {
        iconType: 'property_definition',
        label: 'Property',
        description: 'A property definition. Open it to see its type, description, and where it is used.',
    },
    data_source: {
        iconType: 'data_source',
        label: 'Source',
        description: 'A data source. Open it to see its tables, syncs, and settings.',
    },
    data_model: {
        iconType: 'data_modeling',
        label: 'Table',
        description: 'A table or view in your warehouse. Open it to see its columns, lineage, and data quality.',
    },
    action: {
        label: 'Action',
        description: 'An action. Open it to see the events it matches and how often they happen.',
    },
    // Home. A report has no file system row, so only a pin carries this type.
    [TODAY_REPORT_RECORD_TYPE]: {
        iconType: 'inbox',
        label: 'Report',
        description: 'A self-driving inbox report. Open it to see its evidence, status, and fix.',
    },
    survey: { label: 'Survey', description: 'A survey. Open it to see its questions and responses.' },
    product_tour: {
        label: 'Product tour',
        description: 'A product tour. Open it to see its steps and who has seen it.',
    },
    session_recording_playlist: {
        label: 'Replay playlist',
        description: 'A replay playlist. Open it to watch the recordings in it.',
    },
    endpoints: { label: 'Endpoint', description: 'An endpoint. Open it to see its query and how to call it.' },
}

export function todayRecordType(type: string): TodayRecordType {
    const known = TODAY_RECORD_TYPES[type] ?? TODAY_RECORD_TYPES[type.split('/')[0]]
    if (known) {
        return known
    }
    // A type added to the file system later still says what it is, so its card is never just a name.
    const types: Record<string, { name?: string }> = fileSystemTypes
    const label = types[type]?.name ?? types[type.split('/')[0]]?.name ?? ''
    return {
        label,
        description: label
            ? `${/^[aeiou]/i.test(label) ? 'An' : 'A'} ${label.toLowerCase()}. Open it to see its details.`
            : '',
    }
}
