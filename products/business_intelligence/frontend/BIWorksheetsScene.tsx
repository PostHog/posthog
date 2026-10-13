import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton, LemonTable, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BIStarters } from './BIStarters'
import { biWorksheetsLogic } from './biWorksheetsLogic'

export const scene: SceneExport = { component: BIWorksheetsScene, logic: biWorksheetsLogic }

export function BIWorksheetsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { worksheets, worksheetsLoading, search, page, recent, error } = useValues(biWorksheetsLogic)
    const { setSearch, setPage, setRecent, loadWorksheets } = useActions(biWorksheetsLogic)
    if (!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE]) {
        return <NotFound object="page" />
    }
    return (
        <SceneContent>
            <SceneTitleSection
                name="Worksheets"
                description="Explore your data with visual worksheets."
                resourceType={{ type: 'business_intelligence' }}
                actions={
                    <LemonButton type="primary" icon={<IconPlus />} to={`${urls.businessIntelligenceNew()}#q=`}>
                        New worksheet
                    </LemonButton>
                }
            />
            <BIStarters />
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput type="search" placeholder="Search worksheets" value={search} onChange={setSearch} />
                <LemonSegmentedButton
                    value={recent ? 'recent' : 'all'}
                    onChange={(value) => setRecent(value === 'recent')}
                    options={[
                        { value: 'all', label: 'All worksheets' },
                        { value: 'recent', label: 'Recently viewed' },
                    ]}
                />
            </div>
            {error ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadWorksheets() }}>
                    Couldn't load worksheets.
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={worksheets?.results ?? []}
                    loading={worksheetsLoading}
                    rowKey="id"
                    emptyState={
                        search
                            ? 'No matching worksheets.'
                            : recent
                              ? 'No worksheets viewed in the last 30 days.'
                              : 'Create a worksheet to explore your data.'
                    }
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, worksheet) => (
                                <Link
                                    data-attr="bi-worksheet-link"
                                    to={urls.businessIntelligenceWorksheet(worksheet.short_id)}
                                >
                                    {worksheet.name || worksheet.derived_name || 'Untitled worksheet'}
                                </Link>
                            ),
                        },
                        {
                            title: recent ? 'Last viewed' : 'Last modified',
                            key: 'updated',
                            render: (_, worksheet) =>
                                dayjs(recent ? worksheet.last_viewed_at : worksheet.last_modified_at).fromNow(),
                        },
                    ]}
                    pagination={{
                        controlled: true,
                        currentPage: page,
                        pageSize: 50,
                        entryCount: worksheets?.count ?? 0,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                    }}
                />
            )}
        </SceneContent>
    )
}
