import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { LemonInput } from '@posthog/lemon-ui'

export function PluginsSearch(): JSX.Element {
    const { searchTerm, rearranging } = useValues(pluginsLogic)
    const { setSearchTerm } = useActions(pluginsLogic)
    return (
        <LemonInput
            type="search"
            data-attr="plugins-search"
            placeholder="Start typing to search for an app"
            autoFocus
            value={searchTerm || ''}
            onChange={setSearchTerm}
            disabled={rearranging}
        />
    )
}
