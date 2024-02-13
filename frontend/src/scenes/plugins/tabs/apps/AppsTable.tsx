import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'

import { PluginType } from '~/types'

export function AppsTable({
    title = 'Apps',
    plugins,
    loading,
    renderfn,
}: {
    title?: string
    plugins: (PluginTypeWithConfig | PluginType | PluginRepositoryEntry)[]
    loading: boolean
    renderfn: (plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry) => JSX.Element
}): JSX.Element {
    const [expanded, setExpanded] = useState(true)
    const { searchTerm } = useValues(pluginsLogic)

    return (
        <LemonTable
            dataSource={expanded ? plugins : []}
            loading={loading}
            columns={[
                {
                    title: (
                        <>
                            <LemonButton
                                size="small"
                                sideIcon={!expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                onClick={() => setExpanded(!expanded)}
                                className="-ml-2 mr-2"
                            />
                            {title}
                        </>
                    ),
                    key: 'app',
                    // Passing a function to render after loading
                    render: (_, plugin) => renderfn(plugin),
                },
            ]}
            emptyState={
                !expanded ? (
                    <span className="flex gap-2 items-center">
                        <LemonButton size="small" onClick={() => setExpanded(true)}>
                            Show apps
                        </LemonButton>
                    </span>
                ) : searchTerm ? (
                    'No apps matching your search criteria'
                ) : (
                    'No apps found'
                )
            }
        />
    )
}
