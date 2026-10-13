import { useActions, useAsyncActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonSwitch } from '~/lib/lemon-ui/LemonSwitch'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { atColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmPromptsEmptyState } from '../emptyState/llmPromptsEmptyState'
import { PROMPTS_PER_PAGE, llmPromptsLogic } from './llmPromptsLogic'
import { PromptLabelChip } from './PromptLabelChip'
import { LLMPrompt } from './types'
import { openArchivePromptDialog, openDuplicatePromptDialog, stripPromptSceneSearchParams } from './utils'

// "Prompts open feedback" survey, opened only via the feedback button (its URL targeting never matches).
const PROMPTS_FEEDBACK_SURVEY_ID = '01a0f8a7-bea2-0000-5f58-c8c69e4b7a3b'

export const scene: SceneExport = {
    component: LLMPromptsScene,
    logic: llmPromptsLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
    emptyState: llmPromptsEmptyState,
}

export function LLMPromptsScene(): JSX.Element {
    const { setFilters, deletePrompt, restorePrompt } = useActions(llmPromptsLogic)
    const { duplicatePrompt } = useAsyncActions(llmPromptsLogic)
    const { prompts, promptsLoading, sorting, pagination, filters, promptCountLabel, restoringPromptName } =
        useValues(llmPromptsLogic)
    const { searchParams } = useValues(router)
    const promptUrl = (name: string): string =>
        combineUrl(urls.aiObservabilityPrompt(name), stripPromptSceneSearchParams(searchParams)).url
    const showingArchived = !!filters.archived

    const columns: LemonTableColumns<LLMPrompt> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '25%',
            render: function renderName(_, prompt) {
                // The prompt page only loads active prompts, so an archived row gets no link.
                if (showingArchived) {
                    return <span className="font-semibold">{prompt.name}</span>
                }
                return (
                    <Link to={promptUrl(prompt.name)} className="font-semibold" data-attr="llma-prompt-name-link">
                        {prompt.name}
                    </Link>
                )
            },
        },
        {
            title: 'Prompt',
            dataIndex: 'prompt',
            key: 'prompt',
            width: '40%',
            render: function renderPrompt(prompt) {
                const displayValue = typeof prompt === 'string' ? prompt : JSON.stringify(prompt)
                const truncated = displayValue.length > 100 ? displayValue.slice(0, 100) + '...' : displayValue

                return <span className="text-muted font-mono text-sm">{truncated || <i>–</i>}</span>
            },
        },
        {
            title: 'Latest author',
            dataIndex: 'created_by',
            render: function renderCreatedBy(_, item) {
                const { created_by } = item

                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        {created_by && <ProfilePicture user={created_by} size="md" showName />}
                    </div>
                )
            },
        },
        {
            title: 'Versions',
            dataIndex: 'version_count',
            key: 'version_count',
            width: 100,
            render: function renderVersionCount(_, prompt) {
                return <span className="text-muted-alt">{prompt.version_count}</span>
            },
        },
        // Archiving deletes a prompt's labels, so the archived view has none to show.
        ...(showingArchived
            ? []
            : [
                  {
                      title: 'Labels',
                      key: 'labels',
                      render: function renderLabels(_, prompt) {
                          if (!prompt.all_labels?.length) {
                              return <span className="text-muted-alt">–</span>
                          }
                          return (
                              <div className="flex flex-wrap gap-1">
                                  {prompt.all_labels.map((label) => (
                                      <PromptLabelChip key={label.name} label={`${label.name}: v${label.version}`} />
                                  ))}
                              </div>
                          )
                      },
                  } as LemonTableColumn<LLMPrompt, keyof LLMPrompt | undefined>,
              ]),
        atColumn('created_at', 'Latest version created') as LemonTableColumn<LLMPrompt, keyof LLMPrompt | undefined>,
        {
            width: 0,
            render: function renderMore(_, prompt) {
                if (showingArchived) {
                    return (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                loading={restoringPromptName === prompt.name}
                                disabledReason={
                                    restoringPromptName && restoringPromptName !== prompt.name
                                        ? 'Another prompt is being restored'
                                        : undefined
                                }
                                onClick={() => restorePrompt(prompt.name)}
                                data-attr="llma-prompt-restore"
                            >
                                Restore
                            </LemonButton>
                        </AccessControlAction>
                    )
                }
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={promptUrl(prompt.name)}
                                    data-attr="llma-prompt-dropdown-view"
                                    fullWidth
                                >
                                    View
                                </LemonButton>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        onClick={() =>
                                            openDuplicatePromptDialog(prompt.name, (newName) =>
                                                duplicatePrompt(prompt.name, newName)
                                            )
                                        }
                                        data-attr="llma-prompt-dropdown-duplicate"
                                        fullWidth
                                    >
                                        Duplicate
                                    </LemonButton>
                                </AccessControlAction>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() => openArchivePromptDialog(() => deletePrompt(prompt.name))}
                                        data-attr="llma-prompt-dropdown-delete"
                                        fullWidth
                                    >
                                        Archive
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Prompts"
                description="Track and manage your LLM prompts."
                resourceType={{ type: 'llm_prompts' }}
                actions={
                    <>
                        <FeedbackSurveyButton
                            surveyId={PROMPTS_FEEDBACK_SURVEY_ID}
                            data-attr="prompts-feedback-button"
                        />
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                to={promptUrl('new')}
                                icon={<IconPlusSmall />}
                                data-attr="new-prompt-button"
                            >
                                New prompt
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            <div className="space-y-4">
                <div className="flex gap-x-4 gap-y-2 items-center flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search prompts..."
                        value={filters.search}
                        data-attr="prompts-search-input"
                        onChange={(value) => setFilters({ search: value })}
                        className="max-w-md"
                    />
                    <div className="text-muted-alt">{promptCountLabel}</div>
                    <div className="flex-1" />
                    <span>
                        <b>Created by</b>
                    </span>
                    <MemberSelect
                        defaultLabel="Any user"
                        value={filters.created_by_id ?? null}
                        size="xsmall"
                        onChange={(user) => setFilters({ created_by_id: user?.id, page: 1 })}
                    />
                    <LemonSwitch
                        checked={showingArchived}
                        onChange={(checked) => setFilters({ archived: checked || undefined, page: 1 })}
                        label="Show archived"
                        bordered
                        size="small"
                        data-attr="llma-prompts-show-archived"
                    />
                </div>

                <LemonTable
                    loading={promptsLoading}
                    columns={columns}
                    dataSource={prompts.results}
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
                    loadingSkeletonRows={PROMPTS_PER_PAGE}
                    nouns={['prompt', 'prompts']}
                />
            </div>
        </SceneContent>
    )
}
