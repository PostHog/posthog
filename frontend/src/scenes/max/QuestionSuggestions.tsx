import { IconArrowUpRight, IconGear, IconShuffle } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'

export function QuestionSuggestions(): JSX.Element {
    const { visibleSuggestions, allSuggestionsLoading, dataProcessingAccepted, tools } = useValues(maxLogic)
    const { askMax, shuffleVisibleSuggestions } = useActions(maxLogic)
    const { coreMemoryLoading, coreMemory } = useValues(maxSettingsLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    if (tools.length > 0) {
        return <></>
    }

    if (!coreMemoryLoading && !coreMemory) {
        return (
            <LemonButton
                size="xsmall"
                type="primary"
                onClick={() => askMax('Ready, steady, go!')}
                disabledReason={!dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined}
                center
            >
                Let's get started with me learning about your project!
            </LemonButton>
        )
    }

    return (
        <div className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5 w-[min(48rem,100%)]">
            {
                coreMemoryLoading || allSuggestionsLoading ? (
                    Array.from({ length: 3 }).map((_, index) => (
                        <LemonButton
                            key={index}
                            size="xsmall"
                            type="secondary"
                            disabled
                            style={{
                                width: ['35%', '42.5%', '50%'][index],
                            }}
                        >
                            <LemonSkeleton className="h-3 w-full" />
                        </LemonButton>
                    ))
                ) : visibleSuggestions ? (
                    <>
                        {visibleSuggestions.map((suggestion, index) => (
                            <LemonButton
                                key={index}
                                onClick={() => askMax(suggestion)}
                                size="xsmall"
                                type="secondary"
                                sideIcon={<IconArrowUpRight />}
                                center
                                className="shrink"
                                disabledReason={
                                    !dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined
                                }
                            >
                                {suggestion}
                            </LemonButton>
                        ))}
                        <div className="flex gap-2">
                            <LemonButton
                                onClick={shuffleVisibleSuggestions}
                                size="xsmall"
                                type="secondary"
                                icon={<IconShuffle />}
                                tooltip="Shuffle suggestions"
                            />
                            <LemonButton
                                onClick={() =>
                                    openSettingsPanel({ sectionId: 'environment-max', settingId: 'core-memory' })
                                }
                                size="xsmall"
                                type="secondary"
                                icon={<IconGear />}
                                tooltip="Edit Max's memory"
                            />
                        </div>
                    </>
                ) : null /* Some error */
            }
        </div>
    )
}
