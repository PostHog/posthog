import { useValues } from 'kea'

import { IconMessage, IconRocket } from '@posthog/icons'

import api from 'lib/api'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind, TracesQuery } from '~/queries/schema/schema-general'

import * as earlyAccessFeatureApi from 'products/early_access_features/frontend/generated/api'
import * as errorTrackingApi from 'products/error_tracking/frontend/generated/api'
import * as personsApi from 'products/persons/frontend/generated/api'
import * as replayApi from 'products/replay/frontend/generated/api'
import * as surveysApi from 'products/surveys/frontend/generated/api'
import * as workflowsApi from 'products/workflows/frontend/generated/api'

import { NotebookWidgetPickerKind } from '../notebookWidgetCatalog'
import {
    MarkdownNotebookEntityListPicker,
    MarkdownNotebookEntityListPickerItem,
} from './MarkdownNotebookEntityListPicker'
import { MarkdownNotebookExperimentPicker } from './MarkdownNotebookExperimentPicker'
import { MarkdownNotebookSavedInsightPicker } from './MarkdownNotebookSavedInsightPicker'
import { MarkdownNotebookTaxonomicPicker } from './MarkdownNotebookTaxonomicPicker'

export type MarkdownNotebookEntityPickerKind = NotebookWidgetPickerKind | 'saved-insight'

export type MarkdownNotebookEntityPickerSelection = {
    tagName: string
    props: Record<string, unknown>
}

type MarkdownNotebookEntityPickerProps = {
    action: 'add' | 'select'
    kind: MarkdownNotebookEntityPickerKind | null
    onClose: () => void
    onSelect: (selection: MarkdownNotebookEntityPickerSelection) => void
}

const PICKER_LABELS: Record<MarkdownNotebookEntityPickerKind, string> = {
    'saved-insight': 'Saved insight',
    experiment: 'Experiment',
    'feature-flag': 'Feature flag',
    survey: 'Survey',
    'early-access-feature': 'Early access feature',
    cohort: 'Cohort',
    insight: 'Insight',
    recording: 'Session recording',
    'recording-playlist': 'Recording playlist',
    person: 'Person',
    group: 'Group',
    'error-tracking-issue': 'Error tracking issue',
    'llm-trace': 'LLM trace',
    dashboard: 'Dashboard',
    action: 'Action',
    workflow: 'Workflow',
}

function currentProjectId(): string | null {
    const projectId = teamLogic.values.currentProjectId
    return projectId == null ? null : String(projectId)
}

async function loadSurveyPickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await surveysApi.surveysList(projectId, { limit: 100 })
    return response.results.map((survey) => ({
        id: survey.id,
        name: survey.name,
        description: survey.description,
    }))
}

async function loadEarlyAccessFeaturePickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await earlyAccessFeatureApi.earlyAccessFeatureList(projectId)
    return response.results.map((feature) => ({
        id: feature.id,
        name: feature.name,
        description: feature.description,
    }))
}

async function loadRecordingPickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await replayApi.sessionRecordingsList(projectId, { limit: 100 })
    return response.results.map((recording) => ({
        id: recording.id,
        name: recording.person?.name || recording.distinct_id || recording.id,
        description: recording.start_url,
    }))
}

async function loadRecordingPlaylistPickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await replayApi.sessionRecordingPlaylistsList(projectId, { limit: 100 })
    return response.results.map((playlist) => ({
        id: playlist.short_id,
        name: playlist.name || playlist.derived_name || playlist.short_id,
        description: playlist.description,
    }))
}

async function loadPersonPickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await personsApi.personsList(projectId, { limit: 100 })
    return (response.results || []).map((person) => ({
        id: person.uuid,
        name: person.name,
        description: person.distinct_ids.join(', '),
    }))
}

async function loadErrorTrackingIssuePickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await errorTrackingApi.errorTrackingIssuesList(projectId, { limit: 100 })
    return response.results.map((issue) => ({
        id: issue.id,
        name: issue.name || issue.description || issue.id,
        description: issue.status,
    }))
}

async function loadLLMTracePickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const response = await api.query<TracesQuery>({
        kind: NodeKind.TracesQuery,
        dateRange: { date_from: '-30d' },
        limit: 100,
    })
    return response.results.map((trace) => ({
        id: trace.id,
        name: trace.traceName || trace.id,
        description: trace.distinctId,
    }))
}

async function loadWorkflowPickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const projectId = currentProjectId()
    if (!projectId) {
        return []
    }
    const response = await workflowsApi.hogFlowsList(projectId, { limit: 100 })
    return response.results.map((workflow) => ({
        id: workflow.id,
        name: workflow.name || workflow.id,
        description: workflow.description,
    }))
}

export function MarkdownNotebookEntityPicker({
    action,
    kind,
    onClose,
    onSelect,
}: MarkdownNotebookEntityPickerProps): JSX.Element | null {
    const { groupTypes } = useValues(groupsModel)

    if (!kind) {
        return null
    }

    const label = PICKER_LABELS[kind]
    const title = action === 'add' ? `Add ${label.toLowerCase()} to notebook` : `Select ${label.toLowerCase()}`

    if (kind === 'saved-insight' || kind === 'insight') {
        return (
            <MarkdownNotebookSavedInsightPicker
                isOpen
                title={title}
                onClose={onClose}
                onSelect={(shortId, insightTitle) =>
                    onSelect({
                        tagName: kind === 'insight' ? 'Insight' : 'Query',
                        props:
                            kind === 'insight'
                                ? { id: shortId }
                                : {
                                      query: { kind: 'SavedInsightNode', shortId },
                                      ...(insightTitle ? { title: insightTitle } : {}),
                                  },
                    })
                }
            />
        )
    }

    if (kind === 'experiment') {
        return (
            <MarkdownNotebookExperimentPicker
                isOpen
                title={title}
                onClose={onClose}
                onSelect={(id) => onSelect({ tagName: 'Experiment', props: { id } })}
            />
        )
    }

    if (kind === 'feature-flag' || kind === 'cohort') {
        const tagName = kind === 'feature-flag' ? 'FeatureFlag' : 'Cohort'
        const groupType =
            kind === 'feature-flag' ? TaxonomicFilterGroupType.FeatureFlags : TaxonomicFilterGroupType.Cohorts

        return (
            <MarkdownNotebookTaxonomicPicker
                isOpen
                title={title}
                groupType={groupType}
                onClose={onClose}
                onSelect={(value: TaxonomicFilterValue) => {
                    const id = Number(value)
                    if (Number.isInteger(id) && id > 0) {
                        onSelect({ tagName, props: { id } })
                    } else {
                        onClose()
                    }
                }}
            />
        )
    }

    if (kind === 'action' || kind === 'dashboard') {
        const isAction = kind === 'action'
        return (
            <MarkdownNotebookTaxonomicPicker
                isOpen
                title={title}
                groupType={isAction ? TaxonomicFilterGroupType.Actions : TaxonomicFilterGroupType.Dashboards}
                onClose={onClose}
                onSelect={(value) => {
                    const id = Number(value)
                    if (Number.isInteger(id) && id > 0) {
                        onSelect({ tagName: isAction ? 'Action' : 'Dashboard', props: { id } })
                    } else {
                        onClose()
                    }
                }}
            />
        )
    }

    if (kind === 'group') {
        const groupPickerTypes = Array.from(groupTypes.values()).map(
            (groupType) =>
                `${TaxonomicFilterGroupType.GroupNamesPrefix}_${groupType.group_type_index}` as TaxonomicFilterGroupType
        )

        if (groupPickerTypes.length === 0) {
            return null
        }

        return (
            <MarkdownNotebookTaxonomicPicker
                isOpen
                title={title}
                groupType={groupPickerTypes[0]}
                groupTypes={groupPickerTypes}
                onClose={onClose}
                onSelect={(value, group) => {
                    if (group.groupTypeIndex !== undefined) {
                        onSelect({
                            tagName: 'Group',
                            props: { id: String(value), groupTypeIndex: group.groupTypeIndex },
                        })
                    } else {
                        onClose()
                    }
                }}
            />
        )
    }

    const listPicker = {
        survey: {
            searchPlaceholder: 'Search surveys',
            entityIcon: <IconMessage />,
            loadItems: loadSurveyPickerItems,
            tagName: 'Survey',
        },
        'early-access-feature': {
            searchPlaceholder: 'Search early access features',
            entityIcon: <IconRocket />,
            loadItems: loadEarlyAccessFeaturePickerItems,
            tagName: 'EarlyAccessFeature',
        },
        recording: {
            searchPlaceholder: 'Search session recordings',
            entityIcon: undefined,
            loadItems: loadRecordingPickerItems,
            tagName: 'Recording',
        },
        'recording-playlist': {
            searchPlaceholder: 'Search recording playlists',
            entityIcon: undefined,
            loadItems: loadRecordingPlaylistPickerItems,
            tagName: 'RecordingPlaylist',
        },
        person: {
            searchPlaceholder: 'Search people',
            entityIcon: undefined,
            loadItems: loadPersonPickerItems,
            tagName: 'Person',
        },
        'error-tracking-issue': {
            searchPlaceholder: 'Search error tracking issues',
            entityIcon: undefined,
            loadItems: loadErrorTrackingIssuePickerItems,
            tagName: 'ErrorTrackingIssue',
        },
        'llm-trace': {
            searchPlaceholder: 'Search LLM traces',
            entityIcon: undefined,
            loadItems: loadLLMTracePickerItems,
            tagName: 'LLMTrace',
        },
        workflow: {
            searchPlaceholder: 'Search workflows',
            entityIcon: undefined,
            loadItems: loadWorkflowPickerItems,
            tagName: 'Workflow',
        },
    }[kind]

    if (!listPicker) {
        return null
    }

    return (
        <MarkdownNotebookEntityListPicker
            isOpen
            title={title}
            searchPlaceholder={listPicker.searchPlaceholder}
            entityIcon={listPicker.entityIcon}
            loadItems={listPicker.loadItems}
            onClose={onClose}
            onSelect={(item) =>
                onSelect({
                    tagName: listPicker.tagName,
                    props: { id: String(item.id) },
                })
            }
        />
    )
}
