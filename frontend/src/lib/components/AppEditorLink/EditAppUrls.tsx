import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { Button, List } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { appUrlsLogic } from './appUrlsLogic'
import { UrlRow } from './UrlRow'
import { Spinner } from '../Spinner/Spinner'

export function EditAppUrls({
    actionId,
    allowNavigation = false,
}: {
    actionId?: number
    allowNavigation?: boolean
}): JSX.Element {
    const { appUrls, suggestions, suggestionsLoading } = useValues(appUrlsLogic({ actionId, isToolbarModal: true }))
    const { addUrl, addUrlAndGo, removeUrl, updateUrl } = useActions(appUrlsLogic({ actionId, isToolbarModal: true }))
    const [loadMore, setLoadMore] = useState(false)

    const handleUrlClick = (url: string): void => {
        if (allowNavigation) {
            addUrlAndGo(url)
            return
        }
        addUrl(url)
    }

    return (
        <div>
            <List bordered style={{ background: '#fff', overflow: 'hidden', wordBreak: 'break-all' }}>
                {appUrls.map((url, index) => (
                    <UrlRow
                        key={`${index},${url}`}
                        actionId={actionId}
                        allowNavigation={allowNavigation}
                        url={url}
                        saveUrl={(value) => updateUrl(index, value)}
                        deleteUrl={() => removeUrl(index)}
                    />
                ))}
                {appUrls.length === 0 && (
                    <List.Item className="flex-center">
                        No URLs added yet.
                        {!suggestions ||
                            (suggestions.length > 0 && <> Suggestions: {suggestionsLoading && <Spinner />}</>)}
                    </List.Item>
                )}
                {suggestions &&
                    suggestions.slice(0, loadMore ? suggestions.length : 5).map((url) => (
                        <List.Item
                            key={url}
                            onClick={() => handleUrlClick(url)}
                            style={{ cursor: 'pointer', justifyContent: 'space-between' }}
                        >
                            <a href={url} onClick={(e) => e.preventDefault()} data-attr="app-url-suggestion">
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
            <Button
                type="link"
                onClick={() => addUrl('')}
                style={{ padding: '5px 0', margin: '5px 0', textDecoration: 'none' }}
            >
                + Add URL
            </Button>
        </div>
    )
}
