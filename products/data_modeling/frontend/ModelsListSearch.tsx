import { useActions, useValues } from 'kea'

import { IconInfo, IconSearch } from '@posthog/icons'
import {
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { MODELS_SEARCH_SYNTAX_HELP } from './lineage/SearchSyntaxHelp'
import { modelsListLogic } from './modelsListLogic'
import { VIEW_TYPE_FILTER_OPTIONS, ViewTypeFilter } from './viewsTabLogic'

export function ModelsListSearch(): JSX.Element {
    const { searchTerm, typeFilter } = useValues(modelsListLogic)
    const { setSearchTerm, setTypeFilter } = useActions(modelsListLogic)
    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup className="w-64">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search, +name, or status:failed"
                    aria-label="Search models"
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    data-attr="models-list-search"
                />
                <InputGroupAddon align="inline-end">
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={<span className="inline-flex" aria-label="Search syntax" tabIndex={0} />}
                        >
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent>{MODELS_SEARCH_SYNTAX_HELP}</TooltipContent>
                    </Tooltip>
                </InputGroupAddon>
            </InputGroup>
            <Select
                items={VIEW_TYPE_FILTER_OPTIONS}
                value={typeFilter}
                onValueChange={(next) => setTypeFilter(next as ViewTypeFilter)}
            >
                <SelectTrigger size="sm" aria-label="Model type" data-attr="models-list-type-filter">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {VIEW_TYPE_FILTER_OPTIONS.map(({ value, label }) => (
                        <SelectItem key={value} value={value}>
                            {label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
