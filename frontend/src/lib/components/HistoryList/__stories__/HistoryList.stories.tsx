import React from 'react'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { featureFlagsHistoryResponseJson } from 'lib/components/HistoryList/__stories__/historyMocks'
import { mswDecorator } from '~/mocks/browser'

export default {
    title: 'DataDisplay/HistoryList',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/@current/feature_flags/6/history': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/@current/feature_flags/7/history': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: featureFlagsHistoryResponseJson }),
                ],
            },
        }),
    ],
}

export const WithData = (): JSX.Element => {
    return <HistoryList type={'FeatureFlag'} id={7} />
}

export const WithNoData = (): JSX.Element => {
    return <HistoryList type={'FeatureFlag'} id={6} />
}
