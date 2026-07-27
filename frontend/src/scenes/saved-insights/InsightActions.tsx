import { useActions, useValues } from 'kea'

import { IconHeart, IconHeartFilled, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { BulkSelectionConfig } from 'lib/lemon-ui/LemonTable/useBulkSelection'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, QueryBasedInsightModel } from '~/types'

import { isDraftInsightRow } from './draftInsight'
import { SavedInsightListItem, savedInsightsLogic } from './savedInsightsLogic'

export function InsightFavoriteButton({
    insight,
    size = 'xsmall',
}: {
    insight: QueryBasedInsightModel
    size?: LemonButtonProps['size']
}): JSX.Element {
    const { updateFavoritedInsight } = useActions(savedInsightsLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Insight}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={insight.user_access_level}
        >
            <LemonButton
                size={size}
                onClick={() => updateFavoritedInsight(insight, !insight.favorited)}
                icon={
                    insight.favorited ? (
                        <IconHeartFilled className="text-danger" />
                    ) : (
                        <IconHeart className="text-secondary" />
                    )
                }
                tooltip={`${insight.favorited ? 'Remove from' : 'Add to'} favorite insights`}
            />
        </AccessControlAction>
    )
}

/** Checkbox selection plus the bulk tag/delete actions, shared by the row and table views. */
export function useInsightsBulkSelection(): BulkSelectionConfig<SavedInsightListItem, number> {
    const { bulkDeleteResponseLoading } = useValues(savedInsightsLogic)
    const { loadInsights, bulkDeleteInsights } = useActions(savedInsightsLogic)

    return {
        getKey: (insight: SavedInsightListItem): number => insight.id,
        isRowSelectable: (insight: SavedInsightListItem) =>
            isDraftInsightRow(insight)
                ? { disabledReason: 'This draft only exists in your browser.' }
                : accessLevelSatisfied(
                        AccessControlResourceType.Insight,
                        insight.user_access_level,
                        AccessControlLevel.Editor
                    )
                  ? true
                  : { disabledReason: "You don't have permission to edit this insight." },
        rowAriaLabel: (insight: SavedInsightListItem) => `Select insight ${insight.name || 'Untitled'}`,
        headerAriaLabel: 'Select all insights on this page',
        renderActions: (ctx) => (
            <>
                <BulkUpdateTagsButton
                    resource="insights"
                    selectedIds={ctx.selectedKeys}
                    onSuccess={() => {
                        ctx.clearSelection()
                        loadInsights()
                    }}
                />
                <LemonButton
                    type="primary"
                    status="danger"
                    size="small"
                    icon={<IconTrash />}
                    loading={bulkDeleteResponseLoading}
                    onClick={() => {
                        const count = ctx.selectedCount
                        const noun = count === 1 ? 'insight' : 'insights'
                        LemonDialog.open({
                            title: `Delete ${count} ${noun}?`,
                            description: `Are you sure you want to delete ${count} ${noun}? This action can be undone.`,
                            primaryButton: {
                                children: 'Delete',
                                status: 'danger',
                                onClick: () => {
                                    bulkDeleteInsights({ ids: [...ctx.selectedKeys] })
                                    ctx.clearSelection()
                                },
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    }}
                >
                    Delete selected
                </LemonButton>
            </>
        ),
    }
}

export function InsightMoreMenu({ insight }: { insight: QueryBasedInsightModel }): JSX.Element {
    const { loadInsights, renameInsight, duplicateInsight } = useActions(savedInsightsLogic)
    const { currentProjectId } = useValues(projectLogic)

    return (
        <More
            overlay={
                <>
                    <LemonButton to={urls.insightView(insight.short_id)} fullWidth>
                        View
                    </LemonButton>

                    <LemonDivider />

                    <AccessControlAction
                        resourceType={AccessControlResourceType.Insight}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={insight.user_access_level}
                    >
                        <LemonButton to={urls.insightEdit(insight.short_id)} fullWidth>
                            Edit
                        </LemonButton>
                    </AccessControlAction>

                    <AccessControlAction
                        resourceType={AccessControlResourceType.Insight}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={insight.user_access_level}
                    >
                        <LemonButton
                            onClick={() => renameInsight(insight)}
                            data-attr={`insight-item-${insight.short_id}-dropdown-rename`}
                            fullWidth
                        >
                            Rename
                        </LemonButton>
                    </AccessControlAction>

                    <LemonButton
                        onClick={() => duplicateInsight(insight)}
                        data-attr="duplicate-insight-from-list-view"
                        fullWidth
                    >
                        Duplicate
                    </LemonButton>

                    <LemonDivider />

                    <AccessControlAction
                        resourceType={AccessControlResourceType.Insight}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={insight.user_access_level}
                    >
                        <LemonButton
                            status="danger"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete insight?',
                                    description:
                                        'Are you sure you want to delete this insight? This action can be undone.',
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () =>
                                            void deleteInsightWithUndo({
                                                object: insight,
                                                endpoint: `projects/${currentProjectId}/insights`,
                                                callback: loadInsights,
                                            }),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }}
                            data-attr={`insight-item-${insight.short_id}-dropdown-remove`}
                            fullWidth
                        >
                            Delete insight
                        </LemonButton>
                    </AccessControlAction>
                </>
            }
        />
    )
}
