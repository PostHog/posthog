/**
 * Bridges the legacy `TaxonomicFilterProps` API to the new headless component
 * tree. Used by the entry `<TaxonomicFilter>` component when the
 * `TAXONOMIC_FILTER_HEADLESS` feature flag is on, so existing call-sites get
 * the new implementation without touching their props.
 *
 * Translation table is intentionally narrow for the v1 flip:
 *   - search / tabs / list / select / keyboard nav  → fully wired
 *   - definition popover                            → not yet (legacy renderer
 *                                                      not supported in v1; the
 *                                                      `<Panel>` row uses the
 *                                                      Quill `<ItemMenuItem>`)
 *   - DataWarehouse pinned-row detail-pane          → deferred (see PRD §3.3)
 *   - keyword shortcut promotion in SuggestedFilters → deferred (orchestrator
 *                                                       doesn't yet aggregate
 *                                                       top matches across tabs)
 *
 * Anything in those buckets is documented inline + in the rewrite PRD. When
 * the flag is off, the legacy kea implementation runs exactly as before.
 */
import { KeyboardEvent, useCallback } from 'react'

import { TaxonomicFilterHeadless } from './headless'
import { TaxonomicFilterProps } from './types'

export function TaxonomicFilterAdapter(props: TaxonomicFilterProps): JSX.Element {
    const {
        taxonomicGroupTypes,
        groupType,
        value,
        onChange,
        onEnter,
        onClose,
        optionsFromProp,
        metadataSource,
        eventNames,
        schemaColumns,
        schemaColumnsLoading,
        excludedProperties,
        selectedProperties,
        propertyAllowList,
        showNumericalPropsOnly,
        hideBehavioralCohorts,
        maxContextOptions,
        allowNonCapturedEvents,
        hogQLGlobals,
        hogQLExpressionShowBreakdownLabelHint,
        minSearchQueryLength,
        suggestedFiltersLabel,
        hideSearchInput,
        searchQuery,
        initialSearchQuery,
        enableKeywordShortcuts,
        selectFirstItem = true,
        width,
        height,
    } = props

    // Bridge legacy `onClose` (fires on Escape) by wrapping the orchestrator's
    // keyboard handler at the adapter level — the headless API doesn't ship a
    // dedicated onClose option to keep the surface small.
    const handleKeyDown = useCallback(
        (e: KeyboardEvent<HTMLDivElement>): void => {
            if (e.key === 'Escape') {
                onClose?.()
            }
        },
        [onClose]
    )

    const style = {
        ...(width ? { width: typeof width === 'number' ? `${width}px` : width } : {}),
        ...(height ? { height: typeof height === 'number' ? `${height}px` : height } : {}),
    }

    return (
        <div
            className="taxonomic-filter taxonomic-filter--headless"
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            onKeyDown={handleKeyDown}
        >
            <TaxonomicFilterHeadless.Root
                taxonomicGroupTypes={taxonomicGroupTypes}
                groupType={groupType}
                value={value}
                onChange={onChange}
                onEnter={onEnter}
                searchQuery={searchQuery}
                initialSearchQuery={initialSearchQuery}
                eventNames={eventNames}
                schemaColumns={schemaColumns}
                schemaColumnsLoading={schemaColumnsLoading}
                metadataSource={metadataSource}
                suggestedFiltersLabel={suggestedFiltersLabel}
                excludedProperties={excludedProperties}
                selectedProperties={selectedProperties}
                propertyAllowList={propertyAllowList}
                maxContextOptions={maxContextOptions}
                hideBehavioralCohorts={hideBehavioralCohorts}
                hogQLGlobals={hogQLGlobals}
                hogQLExpressionShowBreakdownLabelHint={hogQLExpressionShowBreakdownLabelHint}
                optionsFromProp={optionsFromProp}
                showNumericalPropsOnly={showNumericalPropsOnly}
                minSearchQueryLength={minSearchQueryLength}
                allowNonCapturedEvents={allowNonCapturedEvents}
                enableKeywordShortcuts={enableKeywordShortcuts}
                selectFirstItem={selectFirstItem}
            >
                {!hideSearchInput && <TaxonomicFilterHeadless.Input />}
                {taxonomicGroupTypes.length > 1 && (
                    <TaxonomicFilterHeadless.Categories className="flex flex-row flex-wrap gap-1 my-2" />
                )}
                <TaxonomicFilterHeadless.Panel className="flex-1 min-h-0 overflow-auto" />
            </TaxonomicFilterHeadless.Root>
        </div>
    )
}
