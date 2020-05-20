import React, { useState } from 'react'
import { kea, useActions, useValues } from 'kea'
import { Spin, Button, List } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

import { userLogic } from 'scenes/userLogic'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { UrlRow } from './UrlRow'
import { toast } from 'react-toastify'

const defaultValue = 'https://'

const appUrlsLogic = kea({
    actions: () => ({
        addUrl: value => ({ value }),
        removeUrl: index => ({ index }),
        updateUrl: (index, value) => ({ index, value }),
    }),

    loaders: ({ values }) => ({
        suggestions: {
            loadSuggestions: async () => {
                let params = {
                    events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                    breakdown: '$current_url',
                }
                let data = await api.get('api/action/trends/?' + toParams(params))
                let domainsSeen = []
                return data
                    .filter(item => {
                        let domain = new URL(item.breakdown_value).hostname
                        if (domainsSeen.indexOf(domain) > -1) return
                        if (values.appUrls.filter(url => url.indexOf(domain) > -1).length > 0) return
                        domainsSeen.push(domain)
                        return true
                    })
                    .map(item => item.breakdown_value)
                    .slice(0, 20)
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadSuggestions,
    }),

    defaults: () => ({
        appUrls: state => userLogic.selectors.user(state).team.app_urls || [defaultValue],
    }),

    allURLs: ({ selectors }) => ({
        recordsForSelectedMonth: [
            () => [selectors.appUrls, selectors.suggestions],
            (appUrls, suggestions) => {
                return appUrls + suggestions
            },
        ],
    }),

    reducers: ({ actions }) => ({
        appUrls: [
            [defaultValue],
            {
                [actions.addUrl]: (state, { value }) => state.concat([value || defaultValue]),
                [actions.updateUrl]: (state, { index, value }) => Object.assign([...state], { [index]: value }),
                [actions.removeUrl]: (state, { index }) => {
                    const newAppUrls = [...state]
                    newAppUrls.splice(index, 1)
                    return newAppUrls
                },
            },
        ],
        suggestions: [
            [],
            {
                [actions.addUrl]: (state, { value }) => [...state].filter(item => value !== item),
            },
        ],
        isSaved: [
            false,
            {
                [actions.addUrl]: () => false,
                [actions.removeUrl]: () => false,
                [actions.updateUrl]: () => false,
                [userLogic.actions.userUpdateSuccess]: (state, { updateKey }) => updateKey === 'SetupAppUrls' || state,
            },
        ],
    }),

    listeners: ({ sharedListeners }) => ({
        addUrl: sharedListeners.saveAppUrls,
        removeUrl: sharedListeners.saveAppUrls,
        updateUrl: sharedListeners.saveAppUrls,
    }),

    sharedListeners: ({ values }) => ({
        saveAppUrls: () => {
            toast('URLs saved', { toastId: 'EditAppUrls' })
            userLogic.actions.userUpdateRequest({ team: { app_urls: values.appUrls } }, 'SetupAppUrls')
        },
    }),
})

export function EditAppUrls({ actionId, allowNavigation }) {
    const { appUrls, suggestions, suggestionsLoading, isSaved } = useValues(appUrlsLogic)
    const { addUrl, removeUrl, updateUrl } = useActions(appUrlsLogic)
    const [loadMore, setLoadMore] = useState()

    return (
        <div>
            <List bordered>
                {appUrls.map((url, index) => (
                    <UrlRow
                        key={`${index},${url}`}
                        actionId={actionId}
                        allowNavigation={allowNavigation}
                        url={url}
                        saveUrl={value => updateUrl(index, value)}
                        deleteUrl={() => removeUrl(index)}
                    />
                ))}
                {appUrls.length === 0 && <List.Item>No url set yet.</List.Item>}
                <List.Item>
                    Suggestions: {suggestionsLoading && <Spin />}{' '}
                    {!suggestionsLoading && suggestions.length === 0 && 'No suggestions found.'}
                </List.Item>
                {suggestions &&
                    suggestions.slice(0, loadMore ? suggestions.length : 5).map(url => (
                        <List.Item
                            key={url}
                            onClick={() => addUrl(url)}
                            style={{ cursor: 'pointer', justifyContent: 'space-between' }}
                        >
                            <a href={url} onClick={e => e.preventDefault()}>
                                {url}
                            </a>
                            <PlusOutlined style={{ color: 'var(--success)' }} />
                        </List.Item>
                    ))}
                {!loadMore && suggestions && suggestions.length > 5 && (
                    <div
                        style={{
                            textAlign: 'center',
                            margin: '12px 0',
                            height: 32,
                            lineHeight: '32px',
                        }}
                    >
                        <Button onClick={() => setLoadMore(true)}>Load more</Button>
                    </div>
                )}
            </List>

            {isSaved && (
                <span className="text-success float-right" style={{ marginLeft: 10 }}>
                    URLs saved.
                </span>
            )}
            <Button
                type="link"
                onClick={() => addUrl()}
                style={{ padding: '5px 0', margin: '5px 0', textDecoration: 'none' }}
            >
                + Add Another URL
            </Button>
        </div>
    )
}
