import { combineUrl, router } from 'kea-router'

import api from 'lib/api'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { EntityListDefinition, defineEntityListScene } from 'lib/components/EntityList'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { createdAtColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, Dataset } from '~/types'

import { DATASETS_ENTITY_TYPE } from './utils'

const DATASETS_PER_PAGE = 30

/** Detail links carry the current search params so returning to the list keeps its page and search. */
function datasetUrl(id: string): string {
    return combineUrl(urls.aiObservabilityDataset(id), router.values.searchParams).url
}

async function deleteDataset(dataset: Dataset, refresh: () => void): Promise<void> {
    try {
        await api.datasets.update(dataset.id, { deleted: true })
        lemonToast.info(`${dataset.name || 'Dataset'} has been deleted.`)
        refresh()
    } catch {
        lemonToast.error('Failed to delete dataset')
    }
}

export const datasetsEntityList: EntityListDefinition<Dataset> = {
    type: DATASETS_ENTITY_TYPE,
    scene: 'AIObservabilityDatasets' as Scene,
    url: urls.aiObservabilityDatasets(),
    nouns: ['dataset', 'datasets'],
    mode: 'server',
    pageSize: DATASETS_PER_PAGE,
    defaultOrderBy: '-created_at',
    load: async ({ search, orderBy, limit, offset }) =>
        await api.datasets.list({ search, order_by: orderBy ?? undefined, limit, offset }),
    search: { placeholder: 'Search datasets...' },
    nameColumn: {
        width: '20%',
        to: (dataset) => datasetUrl(dataset.id),
        render: (dataset) => <>{dataset.name}</>,
    },
    columns: [
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            width: '50%',
            render: (description) => <span className="text-muted">{String(description) || <i>–</i>}</span>,
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, { created_by }) => (
                <div className="flex flex-row items-center flex-nowrap">
                    {created_by && <ProfilePicture user={created_by} size="md" showName />}
                </div>
            ),
        },
        createdAtColumn<Dataset>(),
        updatedAtColumn<Dataset>(),
    ],
    rowMenu: (dataset, { refresh }) => (
        <>
            <LemonButton to={datasetUrl(dataset.id)} data-attr={`dataset-item-${dataset.id}-dropdown-view`} fullWidth>
                View
            </LemonButton>
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    status="danger"
                    onClick={() => void deleteDataset(dataset, refresh)}
                    data-attr={`dataset-item-${dataset.id}-dropdown-delete`}
                    fullWidth
                >
                    Delete
                </LemonButton>
            </AccessControlAction>
        </>
    ),
    newButton: {
        label: 'New dataset',
        to: () => datasetUrl('new'),
        'data-attr': 'create-dataset-button',
        disabledReason: () =>
            getAccessControlDisabledReason(AccessControlResourceType.LlmAnalytics, AccessControlLevel.Editor) ??
            undefined,
    },
}

export const scene = defineEntityListScene(datasetsEntityList)
