import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCheckbox, LemonDropdown, LemonLabel } from '@posthog/lemon-ui'

import { FilterCheckboxList } from 'lib/components/FilterCheckboxList'

import { businessKnowledgeLogic } from '../scenes/businessKnowledgeLogic'
import { SOURCE_TYPE_FILTER_OPTIONS } from '../scenes/filterKnowledgeSources'

export function KnowledgeSourceFiltersDropdown(): JSX.Element {
    const { sourceTypeFilter, learnedOnly } = useValues(businessKnowledgeLogic)
    const appliedCount = sourceTypeFilter.length + (learnedOnly ? 1 : 0)

    return (
        <LemonDropdown closeOnClickInside={false} placement="bottom-start" overlay={<KnowledgeSourceFiltersOverlay />}>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconFilter />}
                active={appliedCount > 0}
                // pinned: autocapture / Playwright key. Do not rename.
                data-attr="business-knowledge-filters-button"
            >
                <span className="flex items-center gap-1">
                    Filters
                    <LemonBadge.Number count={appliedCount} size="small" maxDigits={2} />
                </span>
            </LemonButton>
        </LemonDropdown>
    )
}

function KnowledgeSourceFiltersOverlay(): JSX.Element {
    const { sourceTypeFilter, learnedOnly } = useValues(businessKnowledgeLogic)
    const { setSourceTypeFilter, setLearnedOnly } = useActions(businessKnowledgeLogic)

    return (
        <div className="flex flex-col gap-3 p-2 w-80 max-w-full">
            <div className="flex flex-col gap-1">
                <LemonLabel>Type</LemonLabel>
                <FilterCheckboxList
                    options={SOURCE_TYPE_FILTER_OPTIONS}
                    value={sourceTypeFilter}
                    onChange={setSourceTypeFilter}
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel info="Sources PostHog learned from resolved support tickets">Learned</LemonLabel>
                <LemonButton
                    type="tertiary"
                    size="small"
                    fullWidth
                    icon={<LemonCheckbox checked={learnedOnly} className="pointer-events-none" decorative />}
                    onClick={() => setLearnedOnly(!learnedOnly)}
                    // pinned: autocapture / Playwright key. Do not rename.
                    data-attr="business-knowledge-filter-learned"
                >
                    Support tickets
                </LemonButton>
            </div>
        </div>
    )
}
