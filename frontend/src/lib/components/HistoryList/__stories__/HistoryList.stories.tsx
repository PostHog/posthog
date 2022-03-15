import React from 'react'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { featureFlagsHistoryResponseJson } from 'lib/components/HistoryList/__stories__/historyMocks'
import { useStorybookMocks } from '~/mocks/browser'

export default {
    title: 'DataDisplay/HistoryList',
}

export const WithData = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/projects/@current/feature_flags/7/history': { results: featureFlagsHistoryResponseJson },
        },
    })

    return <HistoryList type={'FeatureFlag'} id={7} />
}

export const WithNoData = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/projects/@current/feature_flags/6/history': { results: [] },
        },
    })

    return <HistoryList type={'FeatureFlag'} id={6} />
}
