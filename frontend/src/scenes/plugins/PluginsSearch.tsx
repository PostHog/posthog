import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export function PluginsSearch(): JSX.Element {
    const { searchTerm } = useValues(pluginsLogic)
    const { setSearchTerm } = useActions(pluginsLogic)
    return (
        <LemonInput
            type="search"
            data-attr="plugins-search"
            placeholder="Search for apps"
            autoFocus
            value={searchTerm || ''}
            onChange={setSearchTerm}
        />
    )
}
