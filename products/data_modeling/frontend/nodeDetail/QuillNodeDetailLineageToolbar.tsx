import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput, Text } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { QuillNodeDetailLineageTypeFilter } from './QuillNodeDetailLineageTypeFilter'

export function QuillNodeDetailLineageToolbar({ id }: { id: string }): JSX.Element {
    const { lineageGraph, lineageSearchTerm, lineageIsFiltered, lineageVisibleNodeIds } = useValues(
        nodeDetailSceneLogic({ id })
    )
    const { setLineageSearchTerm } = useActions(nodeDetailSceneLogic({ id }))

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="min-w-40 max-w-72 flex-1">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search models"
                    aria-label="Search models"
                    value={lineageSearchTerm}
                    onChange={(event) => setLineageSearchTerm(event.target.value)}
                    data-attr="node-detail-lineage-search"
                />
            </InputGroup>
            <QuillNodeDetailLineageTypeFilter id={id} />
            {lineageIsFiltered && (
                <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                    <span>Showing&nbsp;</span>
                    <span translate="no">{pluralize(lineageVisibleNodeIds.size, 'model')}</span>
                    <span>&nbsp;of&nbsp;</span>
                    <span translate="no">{lineageGraph?.nodes.length}</span>
                </Text>
            )}
        </div>
    )
}
