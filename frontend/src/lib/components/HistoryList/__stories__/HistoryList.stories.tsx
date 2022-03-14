import React from 'react'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { resetKeaStory } from 'lib/storybook/kea-story'
import { Provider } from 'kea'
import { defaultHistoryMocks, emptyHistoryMocks } from 'lib/components/HistoryList/__stories__/historyMocks'

export default {
    title: 'PostHog/Components/HistoryList',
}

export const WithData = (): JSX.Element => {
    resetKeaStory()
    defaultHistoryMocks()

    return (
        <Provider>
            <HistoryList type={'FeatureFlag'} id={7} />
        </Provider>
    )
}

export const WithNoData = (): JSX.Element => {
    resetKeaStory()
    emptyHistoryMocks()

    return (
        <Provider>
            <HistoryList type={'FeatureFlag'} id={6} />
        </Provider>
    )
}
