import { actions, connect, kea, listeners, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { CreateQueryEndpointRequest } from '~/types'

import type { queryEndpointLogicType } from './queryEndpointLogicType'

export type CodeExampleTab = 'terminal' | 'python' | 'nodejs'

export interface QueryEndpointLogicProps {}

export const queryEndpointLogic = kea<queryEndpointLogicType>([
    path(['data-warehouse', 'editor', 'sidebar', 'queryEndpointLogic']),
    props({} as QueryEndpointLogicProps),

    connect(() => ({
        values: [],
    })),
    actions({
        setQueryEndpointName: (queryEndpointName: string) => ({ queryEndpointName }),
        setQueryEndpointDescription: (queryEndpointDescription: string) => ({ queryEndpointDescription }),
        setActiveCodeExampleTab: (tab: CodeExampleTab) => ({ tab }),
        createQueryEndpoint: (request: CreateQueryEndpointRequest) => ({ request }),
        createQueryEndpointSuccess: (response: any) => ({ response }),
        createQueryEndpointFailure: (error: any) => ({ error }),
        deleteQueryEndpoint: (name: string) => ({ name }),
        deleteQueryEndpointSuccess: (response: any) => ({ response }),
        deleteQueryEndpointFailure: (error: any) => ({ error }),
    }),
    reducers({
        queryEndpointName: [
            null as string | null,
            { setQueryEndpointName: (_, { queryEndpointName }) => queryEndpointName },
        ],
        queryEndpointDescription: [
            null as string | null,
            { setQueryEndpointDescription: (_, { queryEndpointDescription }) => queryEndpointDescription },
        ],
        activeCodeExampleTab: ['terminal' as CodeExampleTab, { setActiveCodeExampleTab: (_, { tab }) => tab }],
    }),
    listeners(({ actions }) => ({
        createQueryEndpoint: async ({ request }) => {
            try {
                const response = await api.queryEndpoint.create(request)
                actions.createQueryEndpointSuccess(response)
            } catch (error) {
                console.error('Failed to create query endpoint:', error)
                actions.createQueryEndpointFailure(error)
            }
        },
        createQueryEndpointSuccess: () => {
            lemonToast.success(
                <>
                    Query endpoint created successfully!
                    <br />
                    You will be redirected to the query endpoints page.
                </>,
                {
                    onClose: () => {
                        router.actions.push('/embedded-analytics/query-endpoints')
                    },
                }
            )
        },
        createQueryEndpointFailure: ({ error }) => {
            console.error('Failed to create query endpoint:', error)
            lemonToast.error('Failed to create query endpoint')
        },
        deleteQueryEndpoint: async ({ name }) => {
            try {
                // TODO: Add confirmation dialog
                await api.queryEndpoint.delete(name)
                actions.deleteQueryEndpointSuccess(name)
            } catch (error) {
                console.error('Failed to delete query endpoint:', error)
                actions.deleteQueryEndpointFailure(error)
            }
        },
        deleteQueryEndpointSuccess: () => {
            lemonToast.success('Query endpoint deleted successfully')
        },
        deleteQueryEndpointFailure: ({ error }) => {
            console.error('Failed to delete query endpoint:', error)
            lemonToast.error('Failed to delete query endpoint')
        },
    })),
])
