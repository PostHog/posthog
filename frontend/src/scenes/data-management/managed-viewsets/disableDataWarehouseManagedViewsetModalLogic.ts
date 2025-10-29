import { actions, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'
import { DataWarehouseManagedViewsetSavedQuery } from '~/types'

import type { disableDataWarehouseManagedViewsetModalLogicType } from './disableDataWarehouseManagedViewsetModalLogicType'

export const VIEWSET_TITLES: Record<DataWarehouseManagedViewsetKind, string> = {
    revenue_analytics: 'Revenue analytics',
}

export interface DisableDataWarehouseManagedViewsetModalLogicProps {
    type: string
}

export const disableDataWarehouseManagedViewsetModalLogic = kea<disableDataWarehouseManagedViewsetModalLogicType>([
    props({ type: 'root' } as DisableDataWarehouseManagedViewsetModalLogicProps),
    key(({ type }) => `disableDataWarehouseManagedViewsetModalLogic-${type}`),
    path((key) => ['scenes', 'data-management', 'managed-viewsets', key]),

    actions({
        openModal: (kind: DataWarehouseManagedViewsetKind) => ({ kind }),
        closeModal: true,
        setIsDeleting: (isDeleting: boolean) => ({ isDeleting }),
        setConfirmationInput: (confirmationInput: string) => ({ confirmationInput }),
    }),
    reducers({
        isOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        kind: [
            null as DataWarehouseManagedViewsetKind | null,
            {
                openModal: (_, { kind }) => kind,
                closeModal: () => null,
            },
        ],
        isDeleting: [
            false,
            {
                setIsDeleting: (_, { isDeleting }) => isDeleting,
                closeModal: () => false,
            },
        ],
        confirmationInput: [
            '',
            {
                openModal: () => '',
                closeModal: () => '',
                setIsDeleting: () => '',
                setConfirmationInput: (_, { confirmationInput }) => confirmationInput,
            },
        ],
    }),
    loaders(() => ({
        views: [
            [] as DataWarehouseManagedViewsetSavedQuery[],
            {
                openModal: async ({ kind }) => {
                    try {
                        const response = await api.dataWarehouseManagedViewsets.getViews(kind)
                        return response.views
                    } catch (error) {
                        console.error('Failed to fetch views:', error)
                        return []
                    }
                },
            },
        ],
    })),
])
