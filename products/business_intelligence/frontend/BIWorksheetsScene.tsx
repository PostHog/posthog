import { useActions, useMountedLogic, useValues } from 'kea'

import { IconHeart, IconHeartFilled, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton, LemonTable, Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { buildBIAgentContext } from './biAgentContext'
import { biAgentSyncLogic } from './biAgentSyncLogic'
import { BIStarters } from './BIStarters'
import { biWorksheetsLogic } from './biWorksheetsLogic'

const LIBRARY_CONTEXT = buildBIAgentContext()

export const scene: SceneExport = { component: BIWorksheetsScene, logic: biWorksheetsLogic }

export function BIWorksheetsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { worksheets, worksheetsLoading, search, page, recent, createdBy, favorited, error } =
        useValues(biWorksheetsLogic)
    const { setSearch, setPage, setRecent, setCreatedBy, setFavorited, loadWorksheets } = useActions(biWorksheetsLogic)
    useMountedLogic(biAgentSyncLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    useSceneAgentPanel({
        sceneKey: 'business-intelligence',
        contextItems: LIBRARY_CONTEXT,
        active: !!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
        autoOpen: false,
        headlines: ['Build a worksheet from a catalog metric', 'What would you like to explore?'],
    })
    if (!featureFlags[FEATURE_FLAGS.SQL_EDITOR_BI_MODE]) {
        return <NotFound object="page" />
    }
    return (
        <SceneContent>
            <SceneTitleSection
                name="Business intelligence"
                description="Explore your data with visual worksheets."
                resourceType={{ type: 'business_intelligence' }}
                actions={
                    todayRailNav ? (
                        <Button
                            variant="primary"
                            render={<LinkPrimitive to={`${urls.businessIntelligenceNew()}#q=`} />}
                        >
                            <IconPlus />
                            New worksheet
                        </Button>
                    ) : (
                        <LemonButton type="primary" icon={<IconPlus />} to={`${urls.businessIntelligenceNew()}#q=`}>
                            New worksheet
                        </LemonButton>
                    )
                }
            />
            <LemonBanner type="info" dismissKey="business-intelligence-beta-banner">
                <div className="flex flex-col gap-2 @md:flex-row @md:items-center @md:justify-between">
                    <p>Business intelligence is in beta. Tell us what you'd like to see here, or report any issues.</p>
                    {/* Keep one trigger: survey 01a187ee-3e6e-0000-0213-c128d6009577 selects the first matching element. */}
                    <LemonButton
                        type="secondary"
                        id="business-intelligence-feedback-button"
                        data-attr="business-intelligence-feedback-button"
                    >
                        Send feedback
                    </LemonButton>
                </div>
            </LemonBanner>
            <BIStarters />
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search worksheets"
                    aria-label="Search worksheets"
                    value={search}
                    onChange={setSearch}
                    data-attr="bi-worksheets-search"
                />
                <LemonSegmentedButton
                    value={recent ? 'recent' : 'all'}
                    onChange={(value) => setRecent(value === 'recent')}
                    options={[
                        { value: 'all', label: 'All worksheets' },
                        { value: 'recent', label: 'Recently viewed' },
                    ]}
                />
                <MemberSelectMultiplePopover value={createdBy} onChange={setCreatedBy} />
                <LemonButton
                    type="secondary"
                    size="small"
                    active={favorited}
                    aria-pressed={favorited}
                    icon={favorited ? <IconHeartFilled /> : <IconHeart />}
                    onClick={() => setFavorited(!favorited)}
                    data-attr="bi-worksheets-favorites"
                >
                    Favorites
                </LemonButton>
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
                        search || createdBy.length > 0 || favorited
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
                            title: 'Created by',
                            key: 'created_by',
                            render: (_, { created_by }) =>
                                created_by ? (
                                    <ProfilePicture
                                        user={{
                                            first_name: created_by.first_name,
                                            last_name: created_by.last_name,
                                            email: created_by.email,
                                        }}
                                        size="md"
                                        showName
                                    />
                                ) : (
                                    <span className="text-secondary">—</span>
                                ),
                        },
                        {
                            title: recent ? 'Last viewed' : 'Last modified',
                            key: 'updated',
                            render: (_, worksheet) => {
                                const time = recent ? worksheet.last_viewed_at : worksheet.last_modified_at
                                return time ? <TZLabel time={time} /> : <span className="text-secondary">Never</span>
                            },
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
