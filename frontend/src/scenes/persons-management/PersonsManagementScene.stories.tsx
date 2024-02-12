import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

const meta: Meta = {
    title: 'Scenes-App/Persons & Groups',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
    },
    decorators: [],
}
export default meta

export const Persons: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.persons())
    }, [])
    return <App />
}

export const Cohorts: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.cohorts())
    }, [])
    return <App />
}

export const Groups: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.groups(0))
    }, [])
    return <App />
}
