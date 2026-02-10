import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'

import { QueryBasedInsightModel } from '~/types'

import { addJourneyModalLogic } from './addJourneyModalLogic'
import { customerJourneysLogic } from './customerJourneysLogic'

export function AddJourneyModal(): JSX.Element {
    const { isAddJourneyModalOpen } = useValues(customerJourneysLogic)
    const { hideAddJourneyModal, addJourney } = useActions(customerJourneysLogic)
    const { funnels, funnelsLoading, selectedInsight, searchTerm } = useValues(addJourneyModalLogic)
    const { setSearchTerm, setSelectedInsight } = useActions(addJourneyModalLogic)
    const summarizeInsight = useSummarizeInsight()

    const handleAddJourney = (): void => {
        if (selectedInsight) {
            const insight = funnels.find((f) => f.id === selectedInsight)
            if (insight) {
                addJourney({
                    insightId: selectedInsight,
                    name: insight.name || 'Untitled funnel',
                    description: insight.description || undefined,
                })
            }
        }
    }

    return (
        <LemonModal
            isOpen={isAddJourneyModalOpen}
            onClose={hideAddJourneyModal}
            title="Add customer journey"
            description="Select an existing funnel insight to track as a customer journey"
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideAddJourneyModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleAddJourney}
                        disabledReason={!selectedInsight ? 'No insight selected' : null}
                    >
                        Add journey
                    </LemonButton>
                </>
            }
            width="60rem"
        >
            <div className="space-y-4">
                <LemonInput
                    type="search"
                    placeholder="Search funnels..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    autoFocus
                />

                <div className="overflow-x-hidden">
                    <LemonTable
                        dataSource={funnels}
                        columns={[
                            {
                                key: 'id',
                                width: 32,
                                render: function renderType(_, insight) {
                                    return <InsightIcon insight={insight} className="text-secondary text-2xl" />
                                },
                            },
                            {
                                title: 'Name',
                                dataIndex: 'name',
                                key: 'name',
                                render: function renderName(name: string, insight) {
                                    const displayName = name || summarizeInsight(insight.query)
                                    return (
                                        <div className="flex flex-col gap-1 min-w-0">
                                            <span className="block truncate">{name || <i>{displayName}</i>}</span>
                                            {insight.description && (
                                                <div className="text-xs text-tertiary truncate">
                                                    {insight.description}
                                                </div>
                                            )}
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Tags',
                                dataIndex: 'tags' as keyof QueryBasedInsightModel,
                                key: 'tags',
                                render: function renderTags(tags: string[]) {
                                    return <ObjectTags tags={tags} staticOnly />
                                },
                            },
                            {
                                title: 'Last modified',
                                dataIndex: 'last_modified_at',
                                render: function renderLastModified(last_modified_at: string) {
                                    return (
                                        <div className="whitespace-nowrap">
                                            {last_modified_at && <TZLabel time={last_modified_at} />}
                                        </div>
                                    )
                                },
                            },
                        ]}
                        loading={funnelsLoading}
                        rowKey="id"
                        nouns={['funnel', 'funnels']}
                        rowClassName={(insight) =>
                            selectedInsight === insight.id
                                ? 'bg-primary-highlight border-l-2 border-l-primary cursor-pointer'
                                : 'cursor-pointer hover:bg-primary-highlight/30 border-l-2 border-l-transparent'
                        }
                        onRow={(insight) => ({
                            onClick: () => setSelectedInsight(insight.id),
                        })}
                        emptyState={
                            searchTerm ? (
                                <div className="text-muted text-center p-4">No funnels found matching your search</div>
                            ) : (
                                <div className="text-muted text-center p-4">No saved funnel insights found</div>
                            )
                        }
                    />
                </div>
            </div>
        </LemonModal>
    )
}
