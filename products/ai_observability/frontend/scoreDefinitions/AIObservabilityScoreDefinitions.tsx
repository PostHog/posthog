import { useActions, useMountedLogic, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type {
    ScoreDefinitionKindEnumApi as ScoreDefinitionKind,
    ScoreDefinitionApi as ScoreDefinition,
} from '../generated/api.schemas'
import {
    aiObservabilityScoreDefinitionsLogic,
    SCORE_DEFINITIONS_PER_PAGE,
} from './aiObservabilityScoreDefinitionsLogic'
import { ScoreDefinitionActions } from './ScoreDefinitionActions'
import { formatKindLabel } from './scoreDefinitionModalUtils'

const KIND_OPTIONS: { label: string; value: ScoreDefinitionKind | '' }[] = [
    { label: 'All kinds', value: '' },
    { label: 'Categorical', value: 'categorical' },
    { label: 'Numeric', value: 'numeric' },
    { label: 'Boolean', value: 'boolean' },
]

const ARCHIVED_OPTIONS: { label: string; value: '' | 'false' | 'true' }[] = [
    { label: 'Active only', value: 'false' },
    { label: 'All scorers', value: '' },
    { label: 'Archived only', value: 'true' },
]

export function AIObservabilityScoreDefinitions(): JSX.Element {
    const logic = useMountedLogic(aiObservabilityScoreDefinitionsLogic())
    const { setFilters, toggleArchive, loadScoreDefinitions } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showHistory =
        !!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] &&
        !getProductAccessDisabledReason({ sceneKey: Scene.AIObservabilityOfflineScorerHistory })
    const {
        scoreDefinitions,
        scoreDefinitionsLoading,
        scoreDefinitionsError,
        sorting,
        pagination,
        filters,
        scoreDefinitionCountLabel,
        isArchivingDefinition,
    } = useValues(logic)
    const columns: LemonTableColumns<ScoreDefinition> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '25%',
            render: function renderName(_, scoreDefinition) {
                return (
                    <div className="space-y-1">
                        <div className="font-semibold max-w-64 @max-[50rem]/scorers:max-w-32 truncate">
                            <Link to={urls.aiObservabilityScorer(scoreDefinition.id)}>{scoreDefinition.name}</Link>
                        </div>
                        {scoreDefinition.description ? (
                            <div className="max-w-64 @max-[50rem]/scorers:max-w-32 truncate text-muted-alt">
                                {scoreDefinition.description}
                            </div>
                        ) : (
                            <div className="text-muted">No description</div>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Kind',
            dataIndex: 'kind',
            key: 'kind',
            render: function renderKind(kind) {
                return <LemonTag type="muted">{formatKindLabel(kind as ScoreDefinitionKind)}</LemonTag>
            },
        },
        {
            title: 'Version',
            dataIndex: 'current_version',
            key: 'current_version',
            render: function renderVersion(version, scoreDefinition) {
                return scoreDefinition.current_version_id ? (
                    <CopyToClipboardInline
                        description="scorer version ID"
                        explicitValue={scoreDefinition.current_version_id}
                        tooltipMessage="Copy exact version ID"
                    >
                        <span className="font-mono text-xs">v{String(version)}</span>
                    </CopyToClipboardInline>
                ) : (
                    <span className="font-mono text-xs">v{String(version)}</span>
                )
            },
        },
        {
            title: 'Status',
            dataIndex: 'archived',
            key: 'archived',
            render: function renderArchived(archived) {
                return archived ? (
                    <LemonTag type="muted">Archived</LemonTag>
                ) : (
                    <LemonTag type="success">Active</LemonTag>
                )
            },
        },
        {
            ...(updatedAtColumn<ScoreDefinition>() as LemonTableColumn<
                ScoreDefinition,
                keyof ScoreDefinition | undefined
            >),
            className: '@max-[50rem]/scorers:hidden',
        },
        {
            width: 0,
            render: function renderActions(_, scoreDefinition) {
                return (
                    <ScoreDefinitionActions
                        definition={scoreDefinition}
                        archiving={isArchivingDefinition(scoreDefinition.id)}
                        showHistory={showHistory}
                        toggleArchive={toggleArchive}
                    />
                )
            },
        },
    ]

    return (
        <div className="space-y-4 @container/scorers">
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 mb-4 border-b justify-between">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search scorers..."
                        value={filters.search}
                        onChange={(value) => setFilters({ search: value })}
                        className="min-w-64"
                        data-attr="llma-scorers-search-input"
                    />
                    <LemonSelect<ScoreDefinitionKind | ''>
                        value={filters.kind}
                        onChange={(value) => setFilters({ kind: value || '' })}
                        options={KIND_OPTIONS}
                        data-attr="llma-scorers-kind-filter"
                    />
                    <LemonSelect<'' | 'false' | 'true'>
                        value={filters.archived}
                        onChange={(value) => setFilters({ archived: value === '' ? '' : value || 'false' })}
                        options={ARCHIVED_OPTIONS}
                        data-attr="llma-scorers-archived-filter"
                    />
                </div>

                <div className="flex items-center gap-2">
                    <div className="text-muted-alt">{scoreDefinitionCountLabel}</div>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            size="small"
                            to={urls.aiObservabilityScorer('new')}
                            data-attr="llma-scorers-create-button"
                        >
                            New scorer
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            {scoreDefinitionsError && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadScoreDefinitions(false) }}
                >
                    Could not load scorers. Try again.
                </LemonBanner>
            )}
            {!scoreDefinitionsError && (
                <LemonTable
                    loading={scoreDefinitionsLoading}
                    columns={columns}
                    dataSource={scoreDefinitions.results}
                    pagination={pagination}
                    noSortingCancellation
                    sorting={sorting}
                    onSort={(newSorting) =>
                        setFilters({
                            order_by: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                        })
                    }
                    rowKey="id"
                    loadingSkeletonRows={SCORE_DEFINITIONS_PER_PAGE}
                    nouns={['scorer', 'scorers']}
                />
            )}
        </div>
    )
}
