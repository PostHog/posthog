import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Input } from 'antd'

export function PluginsSearch(): JSX.Element {
    const { searchTerm, rearranging } = useValues(pluginsLogic)
    const { setSearchTerm } = useActions(pluginsLogic)
    return (
        <Input.Search
            data-attr="plugins-search"
            placeholder="Start typing to search for an app"
            autoFocus
            value={searchTerm || ''}
            onChange={(e) => setSearchTerm(e.target.value)}
            enterButton
            allowClear
            style={{ maxWidth: 400, marginTop: 5, marginBottom: 10 }}
            disabled={rearranging}
        />
    )
}
