import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import type { DatasetItemReadApi as DatasetItem, DatasetReadApi as Dataset } from '../generated/api.schemas'
import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { aiObservabilityDatasetLogic } from './aiObservabilityDatasetLogic'
import { DatasetItems } from './DatasetItems'
import { datasetsApi } from './datasetsApi'

jest.mock('./datasetsApi', () => ({
    datasetsApi: {
        getDataset: jest.fn(),
        getItem: jest.fn(),
        listDatasets: jest.fn(),
        listItems: jest.fn(),
        listRevisions: jest.fn(),
    },
}))

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN
const DATASET_ID = 'dataset-1'
const TIMESTAMP = '2024-01-01T00:00:00Z'
const TRACE_LINK = '[data-attr="dataset-item-trace-link"]'

const DATASET: Dataset = {
    tags: [],
    id: DATASET_ID,
    name: 'Dataset',
    description: '',
    metadata: {},
    team_id: 997,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    created_by: null,
    archived: false,
    expires_at: null,
    expiring_soon: false,
    current_revision: null,
    current_revision_id: null,
    user_access_level: 'editor',
}

const ITEM_WITHOUT_TRACE: DatasetItem = {
    id: 'item-1',
    dataset: DATASET_ID,
    client_item_id: null,
    version: 1,
    version_id: 'version-1',
    dataset_revision: 1,
    dataset_revision_id: 'revision-1',
    archived: false,
    input: {},
    expected_output: {},
    source_output: null,
    metadata: {},
    source_trace_id: null,
    source_timestamp: null,
    source_event_id: null,
    created_by: null,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    version_created_at: TIMESTAMP,
    version_created_by: null,
    team_id: 997,
}

const ITEM_WITH_TRACE: DatasetItem = {
    ...ITEM_WITHOUT_TRACE,
    id: 'item-2',
    source_trace_id: 'trace-1',
    source_timestamp: TIMESTAMP,
    source_event_id: 'event-1',
}

const ITEM_WITHOUT_TIMESTAMP: DatasetItem = {
    ...ITEM_WITH_TRACE,
    id: 'item-3',
    source_trace_id: 'trace-2',
    source_timestamp: null,
}

describe('DatasetItems', () => {
    let logic: ReturnType<typeof aiObservabilityDatasetLogic.build>

    const traceLink = (): Element => {
        const link = document.querySelector(TRACE_LINK)
        if (!link) {
            throw new Error('No trace link')
        }
        return link
    }

    beforeEach(async () => {
        initKeaTests()
        localStorage.clear()
        const mockDatasetsApi = jest.mocked(datasetsApi)
        mockDatasetsApi.getDataset.mockResolvedValue(DATASET)
        mockDatasetsApi.getItem.mockResolvedValue(ITEM_WITH_TRACE)
        mockDatasetsApi.listDatasets.mockResolvedValue({ results: [], count: 0 })
        mockDatasetsApi.listItems.mockResolvedValue({
            results: [ITEM_WITHOUT_TRACE, ITEM_WITH_TRACE, ITEM_WITHOUT_TIMESTAMP],
            count: 3,
        })
        mockDatasetsApi.listRevisions.mockResolvedValue({ results: [], count: 0 })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: true })
        router.actions.push(urls.aiObservabilityDataset(DATASET_ID))
        logic = aiObservabilityDatasetLogic({ datasetId: DATASET_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        render(
            <BindLogic logic={aiObservabilityDatasetLogic} props={{ datasetId: DATASET_ID }}>
                <DatasetItems dataset={DATASET} />
            </BindLogic>
        )
        await waitFor(() => expect(document.querySelector(TRACE_LINK)).not.toBeNull())
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('opens the drawer on the source event from the trace link', () => {
        fireEvent.click(traceLink())

        expect(router.values.location.pathname).toContain(urls.aiObservabilityDataset(DATASET_ID))
        expect(router.values.searchParams).toEqual({ trace: 'trace-1', ts: TIMESTAMP, step: 'event-1' })
    })

    it('does nothing on a click elsewhere in the row', () => {
        const row = traceLink().closest('tr')
        if (!row) {
            throw new Error('No row')
        }

        fireEvent.click(within(row).getByText('Active'))

        expect(router.values.location.pathname).toContain(urls.aiObservabilityDataset(DATASET_ID))
        expect(router.values.searchParams).toEqual({})
    })

    it('gives the drawer only the rows that show a trace link', () => {
        expect(traceDrawerLogic({ listId: 'dataset-items' }).values.rows).toEqual([
            { traceId: 'trace-1', timestamp: TIMESTAMP, stepId: 'event-1' },
        ])
    })

    it('still opens the item modal from the ID link', () => {
        const idLink = document.querySelector('[data-attr="dataset-item-open"]')
        if (!idLink) {
            throw new Error('No ID link')
        }

        fireEvent.click(idLink)

        expect(router.values.searchParams).toMatchObject({ item: ITEM_WITHOUT_TRACE.id })
        expect(logic.values.isDatasetItemModalOpen).toBe(true)
    })
})
