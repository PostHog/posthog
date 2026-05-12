import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonRadio, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { WatchedQuestionCadence, watchedQuestionsLogic } from './watchedQuestionsLogic'
import { watchThisAnswerModalLogic } from './watchThisAnswerModalLogic'

const CADENCE_OPTIONS: { value: WatchedQuestionCadence; label: string; description: string }[] = [
    { value: 'daily', label: 'Daily', description: 'Re-evaluated every 24 hours' },
    {
        value: 'weekly',
        label: 'Weekly',
        description: 'Re-evaluated every 7 days — recommended for most metrics',
    },
    { value: 'monthly', label: 'Monthly', description: 'Re-evaluated every 30 days' },
]

export function WatchThisAnswerModal(): JSX.Element {
    const { isOpen, prefill, knownRepositories } = useValues(watchThisAnswerModalLogic)
    const { closeModal } = useActions(watchThisAnswerModalLogic)
    const { createWatchedQuestion } = useActions(watchedQuestionsLogic)
    const { watchedQuestionsLoading } = useValues(watchedQuestionsLogic)

    const [title, setTitle] = useState('')
    const [cadence, setCadence] = useState<WatchedQuestionCadence>('weekly')
    const [repository, setRepository] = useState<string>('')

    useEffect(() => {
        if (isOpen) {
            setTitle(prefill?.title || '')
            setCadence('weekly')
            setRepository('')
        }
    }, [isOpen, prefill])

    if (!prefill) {
        return <></>
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Watch this answer"
            description="Max will re-run this question on a schedule and notify Signals if the answer materially changes."
            footer={
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={watchedQuestionsLoading}
                        disabledReason={!title ? 'Give the watch a short title' : null}
                        onClick={() => {
                            createWatchedQuestion({
                                conversation_id: prefill.conversationId,
                                human_message_id: prefill.humanMessageId,
                                visualization_message_id: prefill.visualizationMessageId,
                                title,
                                cadence,
                                repository: repository || undefined,
                            })
                            closeModal()
                        }}
                    >
                        Start watching
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonField.Pure label="Title" htmlFor="watch-title">
                    <LemonInput id="watch-title" value={title} onChange={setTitle} maxLength={255} />
                </LemonField.Pure>

                <LemonField.Pure label="Cadence">
                    <LemonRadio
                        value={cadence}
                        onChange={(value) => setCadence(value as WatchedQuestionCadence)}
                        options={CADENCE_OPTIONS.map((option) => ({
                            value: option.value,
                            label: option.label,
                            description: option.description,
                        }))}
                    />
                </LemonField.Pure>

                <LemonField.Pure
                    label="Repository for PRs (optional)"
                    info="If set, drift signals will pin the resulting Signals → Tasks → PR pipeline to this repo."
                >
                    <LemonSelect
                        value={repository}
                        onChange={(v) => setRepository(v || '')}
                        options={[
                            { value: '', label: 'No repo (notify only via Signals)' },
                            ...knownRepositories.map((repo) => ({ value: repo, label: repo })),
                        ]}
                        placeholder="Pick a connected GitHub repository…"
                    />
                </LemonField.Pure>

                <LemonBanner type="info" icon={<IconInfo />}>
                    Your question text and a snapshot of the result will be reprocessed by AI on each run.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
