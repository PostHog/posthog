import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Input } from 'antd'

export function PluginsSearch(): JSX.Element {
    const { searchTerm, rearranging } = useValues(pluginsLogic)
    const { setSearchTerm } = useActions(pluginsLogic)
    return (
        <Input
            placeholder="Start typing to search for a plugin"
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ maxWidth: 400, height: 40, borderRadius: 5, marginTop: 5, marginBottom: 10 }}
            disabled={rearranging}
            value={searchTerm || ''}
            allowClear
        />
    )
}
