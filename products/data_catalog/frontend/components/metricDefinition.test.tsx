import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { MetricDefinition } from './MetricDefinition'

const SOURCE_INSIGHT_ACTION = 'View source insight'

function buildMetric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'weekly_file_uploads',
        description: 'Weekly file uploads',
        definition_kind: 'TrendsQuery',
        definition: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: 'uploaded_file' }] },
        source_insight_short_id: null,
        status: 'proposed',
        is_drifted: false,
        owner: null,
        ...overrides,
    } as DataCatalogMetricApi
}

function renderDefinition(metric: DataCatalogMetricApi): void {
    render(
        <MetricDefinition
            metric={metric}
            editingDefinition={false}
            draftMarkdown=""
            saving={false}
            runResult={null}
            runResultLoading={false}
            onDraftMarkdown={jest.fn()}
            onEdit={jest.fn()}
            onStartEditingMarkdown={jest.fn()}
            onSaveMarkdown={jest.fn()}
            onRun={jest.fn()}
            onRunWithAI={jest.fn()}
        />
    )
}

describe('MetricDefinition', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a SQL metric', 'HogQLQuery'],
        ['a structured-query metric', 'TrendsQuery'],
    ])('links back to the source insight for %s that has one', (_label, definitionKind) => {
        renderDefinition(buildMetric({ definition_kind: definitionKind, source_insight_short_id: 'abc123' }))

        expect(screen.getByText(SOURCE_INSIGHT_ACTION)).toBeInTheDocument()
    })

    it('offers the definition instead of claiming an insight when none is linked', () => {
        renderDefinition(buildMetric({ source_insight_short_id: null }))

        // The panel used to claim every non-SQL, non-markdown metric came from an insight, leaving
        // the reader with copy that pointed at nothing.
        expect(screen.queryByText(/derived from an insight/)).not.toBeInTheDocument()
        expect(screen.queryByText(SOURCE_INSIGHT_ACTION)).not.toBeInTheDocument()
        expect(screen.getByText('View definition')).toBeInTheDocument()
    })
})
