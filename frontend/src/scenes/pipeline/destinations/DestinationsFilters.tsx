import { LemonBanner, LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { PipelineBackend } from '../types'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'

export type DestinationsFiltersProps = {
    hideSearch?: boolean
    hideShowPaused?: boolean
    hideKind?: boolean
}

export function DestinationsFilters({
    hideSearch,
    hideShowPaused,
    hideKind,
}: DestinationsFiltersProps): JSX.Element | null {
    const { user, filters } = useValues(destinationsFiltersLogic)
    const { setFilters, openFeedbackDialog } = useActions(destinationsFiltersLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const hogFunctionsEnabled = !!useFeatureFlag('HOG_FUNCTIONS')

    return (
        <div className="space-y-2">
            <FlaggedFeature flag="hog-functions" match={false}>
                <LemonBanner
                    type="info"
                    action={{
                        onClick: () => openSidePanel(SidePanelTab.FeaturePreviews),
                        children: 'Enable feature preview',
                    }}
                >
                    We're excited to announce <b>Destinations 3000</b> - the new version of our realtime destinations
                    that include a range of pre-built templates, native filtering, templating and even customizing the
                    code.
                </LemonBanner>
            </FlaggedFeature>

            <div className="flex items-center gap-2">
                {!hideSearch && (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                )}
                <Link className="text-sm font-semibold" subtle onClick={() => openFeedbackDialog()}>
                    Can't find what you're looking for?
                </Link>
                <div className="flex-1" />
                {typeof hideShowPaused !== 'boolean' && (
                    <LemonCheckbox
                        label="Show paused"
                        bordered
                        size="small"
                        checked={filters.showPaused}
                        onChange={(e) => setFilters({ showPaused: e ?? undefined })}
                    />
                )}
                {(user?.is_staff || user?.is_impersonated) && (
                    <LemonCheckbox
                        label="Show hidden"
                        bordered
                        size="small"
                        checked={filters.showHidden}
                        onChange={(e) => setFilters({ showHidden: e ?? undefined })}
                    />
                )}

                {!hideKind && (
                    <LemonSelect
                        type="secondary"
                        size="small"
                        options={
                            [
                                { label: 'All kinds', value: null },
                                hogFunctionsEnabled
                                    ? { label: 'Realtime (new)', value: PipelineBackend.HogFunction }
                                    : undefined,
                                { label: 'Realtime', value: PipelineBackend.Plugin },
                                { label: 'Batch exports', value: PipelineBackend.BatchExport },
                            ].filter(Boolean) as { label: string; value: PipelineBackend | null }[]
                        }
                        value={filters.kind ?? null}
                        onChange={(e) => setFilters({ kind: e ?? null })}
                    />
                )}
            </div>
        </div>
    )
}
