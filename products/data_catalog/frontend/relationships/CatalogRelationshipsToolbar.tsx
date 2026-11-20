import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh, IconSearch } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, InputGroupInput } from '@posthog/quill'

import { viewLinkLogic } from 'products/data_warehouse/frontend/shared/logics/viewLinkLogic'

import { relationshipsLogic } from '../relationshipsLogic'
import { CatalogRelationshipsFilterMenu } from './CatalogRelationshipsFilterMenu'

export function CatalogRelationshipsToolbar(): JSX.Element {
    const { filters, proposalsLoading, joinsLoading } = useValues(relationshipsLogic)
    const { setFilters, loadProposals, loadJoins, openProposal } = useActions(relationshipsLogic)
    const { toggleNewJoinModal } = useActions(viewLinkLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="w-full @min-[40rem]/main-content:w-72">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search relationships"
                    aria-label="Search relationships"
                    value={filters.search}
                    onChange={(event) => setFilters({ search: event.target.value })}
                    data-attr="data-catalog-relationships-search"
                />
            </InputGroup>
            <CatalogRelationshipsFilterMenu />
            <div className="ml-auto flex flex-wrap items-center gap-2">
                <Button
                    size="icon"
                    aria-label="Reload relationships"
                    tooltip="Reload relationships"
                    className="text-muted-foreground"
                    loading={proposalsLoading || joinsLoading}
                    onClick={() => {
                        loadProposals()
                        loadJoins()
                    }}
                    data-attr="data-catalog-relationships-reload"
                >
                    <IconRefresh />
                </Button>
                <Button variant="outline" onClick={() => openProposal()} data-attr="data-catalog-relationships-propose">
                    Propose a relationship
                </Button>
                <Button variant="primary" onClick={() => toggleNewJoinModal()} data-attr="data-catalog-new-join">
                    <IconPlus />
                    New join
                </Button>
            </div>
        </div>
    )
}
