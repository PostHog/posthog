import { useActions, useValues } from 'kea'

import { IconChevronDown, IconSearch, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

import { offlineExperimentsLogic, type OfflineExperimentsLogicProps } from './offlineExperimentsLogic'

export function OfflineScoreChooser(props: OfflineExperimentsLogicProps): JSX.Element {
    const logic = offlineExperimentsLogic(props)
    const {
        chooserOpen,
        draftScorerIds,
        scorerOptions,
        scorersById,
        scorerOptionsLoading,
        scorerOptionsError,
        scorerSearch,
        scorerOffset,
    } = useValues(logic)
    const { closeChooser, saveScorers, setDraftScorerIds, setScorerSearch, setScorerOffset, loadOfflineScorerOptions } =
        useActions(logic)
    const move = (index: number, offset: number): void => {
        const next = [...draftScorerIds]
        ;[next[index], next[index + offset]] = [next[index + offset], next[index]]
        setDraftScorerIds(next)
    }
    return (
        <LemonModal
            title="Choose scores"
            isOpen={chooserOpen}
            onClose={closeChooser}
            width={720}
            footer={
                <>
                    <LemonButton onClick={closeChooser}>Cancel</LemonButton>
                    <LemonButton type="primary" onClick={saveScorers} data-attr="offline-score-selection-save">
                        Save choices
                    </LemonButton>
                </>
            }
        >
            <p>Choose the scores to follow above your recent experiments. Your choices are saved in this browser.</p>
            <div className="@container">
                <div className="grid gap-4 @min-[32rem]:grid-cols-2">
                    <div className="min-w-0 space-y-3">
                        <LemonInput
                            prefix={<IconSearch />}
                            type="search"
                            value={scorerSearch}
                            onChange={setScorerSearch}
                            placeholder="Search scorers"
                        />
                        <div className="h-48 @min-[32rem]:h-64 overflow-y-auto space-y-3">
                            {scorerOptionsLoading ? (
                                <LemonSkeleton className="h-full" />
                            ) : scorerOptionsError ? (
                                <LemonBanner
                                    type="error"
                                    action={{ children: 'Retry', onClick: loadOfflineScorerOptions }}
                                >
                                    Could not load scorers.
                                </LemonBanner>
                            ) : scorerOptions ? (
                                <>
                                    {scorerOptions.results.map((scorer) => (
                                        <LemonCheckbox
                                            key={scorer.id}
                                            checked={draftScorerIds.includes(scorer.id)}
                                            label={`${scorer.name} (${scorer.kind})${scorer.archived ? ' · Archived' : ''}`}
                                            onChange={(checked) =>
                                                setDraftScorerIds(
                                                    checked
                                                        ? [...draftScorerIds, scorer.id]
                                                        : draftScorerIds.filter((id) => id !== scorer.id)
                                                )
                                            }
                                        />
                                    ))}
                                    {scorerOptions.results.length === 0 && (
                                        <p className="text-muted">No scorers match this search.</p>
                                    )}
                                </>
                            ) : null}
                        </div>
                        <div className="flex justify-between items-center h-8 gap-2">
                            {scorerOptions && (
                                <>
                                    <span className="text-muted text-xs">{`${scorerOptions.count} scorers`}</span>
                                    <div className="flex gap-1">
                                        <LemonButton
                                            size="small"
                                            disabledReason={scorerOffset === 0 ? 'First page' : undefined}
                                            onClick={() => setScorerOffset(scorerOffset - 50)}
                                        >
                                            Previous
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            disabledReason={
                                                scorerOffset + 50 >= scorerOptions.count ? 'Last page' : undefined
                                            }
                                            onClick={() => setScorerOffset(scorerOffset + 50)}
                                        >
                                            Next
                                        </LemonButton>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                    <div className="min-w-0 space-y-3">
                        <h4 className="mb-0">Chart order</h4>
                        <div className="h-32 @min-[32rem]:h-80 overflow-y-auto space-y-1">
                            {draftScorerIds.length === 0 && (
                                <p className="text-muted">Select scores to add them to your overview.</p>
                            )}
                            {draftScorerIds.map((id, index) => (
                                <div key={id} className="flex items-center gap-1 min-w-0">
                                    <span className="flex-1 truncate">{scorersById[id]?.name || id}</span>
                                    <LemonButton
                                        icon={<IconChevronDown className="rotate-180" />}
                                        aria-label="Move score up"
                                        size="xsmall"
                                        disabledReason={index === 0 ? 'Already first' : undefined}
                                        onClick={() => move(index, -1)}
                                    />
                                    <LemonButton
                                        icon={<IconChevronDown />}
                                        aria-label="Move score down"
                                        size="xsmall"
                                        disabledReason={
                                            index === draftScorerIds.length - 1 ? 'Already last' : undefined
                                        }
                                        onClick={() => move(index, 1)}
                                    />
                                    <LemonButton
                                        icon={<IconX />}
                                        aria-label="Remove score"
                                        size="xsmall"
                                        onClick={() =>
                                            setDraftScorerIds(draftScorerIds.filter((selected) => selected !== id))
                                        }
                                    />
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
