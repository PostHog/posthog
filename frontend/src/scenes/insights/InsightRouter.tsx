import { Skeleton } from 'antd'
import { kea, useValues } from 'kea'
import { router, combineUrl } from 'kea-router'
import api from 'lib/api'
import { Link } from 'lib/components/Link'
import React from 'react'
import { DashboardItemType } from '~/types'
import { insightRouterLogicType } from './InsightRouterType'

const insightRouterLogic = kea<insightRouterLogicType<DashboardItemType>>({
    actions: {
        loadInsight: (id: string) => ({ id }),
        setError: true,
    },
    reducers: {
        error: [
            false,
            {
                setError: () => true,
            },
        ],
    },
    listeners: ({ actions }) => ({
        loadInsight: async ({ id }) => {
            const response = await api.get(`api/insight/?short_id=${id}`)
            if (response.results.length) {
                const item = response.results[0] as DashboardItemType
                router.actions.push(
                    combineUrl('/insights', item.filters, {
                        fromItem: item.id,
                        fromItemName: item.name,
                        fromDashboard: item.dashboard,
                        id: item.short_id,
                    }).url
                )
            } else {
                actions.setError()
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/i/:id': ({ id }: { id: string }) => {
            actions.loadInsight(id)
        },
    }),
})

/* Handles insights short links `/i/{id}` */
export function InsightRouter(): JSX.Element {
    const { error } = useValues(insightRouterLogic)
    return (
        <>
            {error ? (
                <div className="dashboard not-found">
                    <div className="graphic" />
                    <h1 className="page-title">Insight not found</h1>
                    <b>It seems this page may have been lost in space.</b>
                    <p>
                        It’s possible this insight may have been deleted or its sharing settings changed. Please check
                        with the person who sent you here, or{' '}
                        <Link
                            to="https://posthog.com/support?utm_medium=in-product&utm_campaign=insight-not-found"
                            target="_blank"
                            rel="noopener"
                        >
                            contact support
                        </Link>{' '}
                        if you think this is a mistake.
                    </p>
                </div>
            ) : (
                <>
                    <Skeleton active />
                </>
            )}
        </>
    )
}
