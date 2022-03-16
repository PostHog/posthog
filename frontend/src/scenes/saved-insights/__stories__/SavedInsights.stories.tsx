import { Meta } from '@storybook/react'

import { SavedInsights } from '../SavedInsights'
import insightsJson from './insights.json'

import React, { useEffect } from 'react'
import { router } from 'kea-router'
import { mswDecorator } from '~/mocks/browser'

export default {
    title: '___TO CLEAN/SavedInsights',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/1/insights': insightsJson,
            },
        }),
    ],
} as Meta

export const ListView = (): JSX.Element => {
    useEffect(() => {
        router.actions.push('/insights')
    })
    return <SavedInsights />
}

export const CardView = (): JSX.Element => {
    useEffect(() => {
        router.actions.push('/insights?layoutView=card')
    })
    return <SavedInsights />
}
