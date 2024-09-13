import { LemonBanner, LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { PipelineBackend } from '../types'
import { destinationsFiltersLogic, DestinationsFiltersLogicProps } from './destinationsFiltersLogic'

export function DestinationsFilters(props: DestinationsFiltersLogicProps): JSX.Element | null {
    const { filters } = useValues(destinationsFiltersLogic(props))
    const { setFilters, openFeedbackDialog } = useActions(destinationsFiltersLogic(props))
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
                {!props.forceFilters?.search && (
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
                {typeof props.forceFilters?.showPaused !== 'boolean' && (
                    <LemonCheckbox
                        label="Show paused"
                        bordered
                        size="small"
                        checked={filters.showPaused}
                        onChange={(e) => setFilters({ showPaused: e ?? undefined })}
                    />
                )}
                {!props.forceFilters?.kind && (
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
