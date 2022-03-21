import React from 'react'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { featureFlagsHistoryResponseJson } from 'lib/components/HistoryList/__mocks__/historyListMocks'
import { mswDecorator } from '~/mocks/browser'
import { ComponentMeta } from '@storybook/react'

export default {
    title: 'Components/History List',
    component: HistoryList,
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
} as ComponentMeta<typeof HistoryList>

export function WithData(): JSX.Element {
    return <HistoryList type={'FeatureFlag'} id={7} />
}

export function WithNoData(): JSX.Element {
    return <HistoryList type={'FeatureFlag'} id={6} />
}
