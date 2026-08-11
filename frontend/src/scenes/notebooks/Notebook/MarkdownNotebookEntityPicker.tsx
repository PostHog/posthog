import { IconMessage, IconRocket } from '@posthog/icons'

import api from 'lib/api'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

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
}

async function loadSurveyPickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const response = await api.surveys.list({ limit: 100 })
    return response.results.map((survey) => ({
        id: survey.id,
        name: survey.name,
        description: survey.description,
    }))
}

async function loadEarlyAccessFeaturePickerItems(): Promise<MarkdownNotebookEntityListPickerItem[]> {
    const response = await api.earlyAccessFeatures.list()
    return response.results.map((feature) => ({
        id: feature.id,
        name: feature.name,
        description: feature.description,
    }))
}

export function MarkdownNotebookEntityPicker({
    action,
    kind,
    onClose,
    onSelect,
}: MarkdownNotebookEntityPickerProps): JSX.Element | null {
    if (!kind) {
        return null
    }

    const label = PICKER_LABELS[kind]
    const title = action === 'add' ? `Add ${label.toLowerCase()} to notebook` : `Select ${label.toLowerCase()}`

    if (kind === 'saved-insight') {
        return (
            <MarkdownNotebookSavedInsightPicker
                isOpen
                onClose={onClose}
                onSelect={(shortId, insightTitle) =>
                    onSelect({
                        tagName: 'Query',
                        props: {
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

    const isSurvey = kind === 'survey'
    return (
        <MarkdownNotebookEntityListPicker
            isOpen
            title={title}
            searchPlaceholder={isSurvey ? 'Search surveys' : 'Search early access features'}
            entityIcon={isSurvey ? <IconMessage /> : <IconRocket />}
            loadItems={isSurvey ? loadSurveyPickerItems : loadEarlyAccessFeaturePickerItems}
            onClose={onClose}
            onSelect={(item) =>
                onSelect({
                    tagName: isSurvey ? 'Survey' : 'EarlyAccessFeature',
                    props: { id: String(item.id) },
                })
            }
        />
    )
}
