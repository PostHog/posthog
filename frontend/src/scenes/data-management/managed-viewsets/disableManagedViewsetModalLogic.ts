import { actions, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ManagedViewsetKind } from '~/queries/schema/schema-general'

import { ManagedViewsetView } from './ManagedViewsetImpactModal'
import type { disableManagedViewsetModalLogicType } from './disableManagedViewsetModalLogicType'

export const VIEWSET_TITLES: Record<ManagedViewsetKind, string> = {
    revenue_analytics: 'Revenue analytics',
}

export interface DisableManagedViewsetModalLogicProps {
    type: string
}

export const disableManagedViewsetModalLogic = kea<disableManagedViewsetModalLogicType>([
    props({ type: 'root' } as DisableManagedViewsetModalLogicProps),
    key(({ type }) => `disableManagedViewsetModalLogic-${type}`),
    path((key) => ['scenes', 'data-management', 'managed-viewsets', key]),

    actions({
        openModal: (kind: ManagedViewsetKind) => ({ kind }),
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
            null as ManagedViewsetKind | null,
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
            [] as ManagedViewsetView[],
            {
                openModal: async ({ kind }) => {
                    try {
                        const response = await api.managedViewsets.getViews(kind)
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
