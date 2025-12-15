import { IconCheck, IconX } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'

import { Prompt, Topic } from '../types'

interface TopicCompetitorBreakdownModalProps {
    isOpen: boolean
    onClose: () => void
    topic: Topic | null
    competitor: string | null
    brandName: string
}

export function TopicCompetitorBreakdownModal({
    isOpen,
    onClose,
    topic,
    competitor,
    brandName,
}: TopicCompetitorBreakdownModalProps): JSX.Element | null {
    if (!isOpen || !topic || !competitor) {
        return null
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`${topic.name}: ${brandName} vs ${competitor}`}
            width={800}
        >
            <LemonModal.Content>
                <div className="flex flex-col gap-2">
                    <div className="grid grid-cols-[1fr_100px_100px] gap-2 pb-2 border-b font-semibold text-sm">
                        <div>Prompt</div>
                        <div className="text-center">{brandName}</div>
                        <div className="text-center">{competitor}</div>
                    </div>
                    <div className="max-h-[60vh] overflow-y-auto">
                        {topic.prompts.map((prompt: Prompt) => {
                            const brandMentioned = prompt.you_mentioned
                            const competitorMentioned = prompt.competitors_mentioned.includes(competitor)

                            return (
                                <div
                                    key={prompt.id}
                                    className="grid grid-cols-[1fr_100px_100px] gap-2 py-2 border-b border-border-light items-center"
                                >
                                    <div className="text-sm">{prompt.text}</div>
                                    <div className="flex justify-center">
                                        {brandMentioned ? (
                                            <IconCheck className="text-success w-5 h-5" />
                                        ) : (
                                            <IconX className="text-muted w-5 h-5" />
                                        )}
                                    </div>
                                    <div className="flex justify-center">
                                        {competitorMentioned ? (
                                            <IconCheck className="text-success w-5 h-5" />
                                        ) : (
                                            <IconX className="text-muted w-5 h-5" />
                                        )}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                    <div className="pt-2 text-sm text-muted">{topic.prompts.length} prompts in this topic</div>
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
