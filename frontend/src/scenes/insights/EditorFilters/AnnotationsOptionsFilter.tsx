import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationsFilter } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

function summarizeAnnotationsFilter(annotationsFilter: AnnotationsFilter | null | undefined): string {
    const parts = [annotationsFilter?.emojis?.join(' '), annotationsFilter?.search && `"${annotationsFilter.search}"`]
    return parts.filter(Boolean).join(' · ') || 'All'
}

export function AnnotationsOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations, annotationsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { annotations } = useValues(annotationsModel)

    const enabled = showAnnotations !== false
    // updateInsightFilter debounces, so patches merge into a local draft to keep rapid emoji clicks.
    const [draft, setDraft] = useState(annotationsFilter ?? undefined)
    useEffect(() => setDraft(annotationsFilter ?? undefined), [annotationsFilter])
    const selectedEmojis = draft?.emojis ?? []
    const [searchDraft, setSearchDraft] = useState(draft?.search ?? '')
    useEffect(() => setSearchDraft(draft?.search ?? ''), [draft?.search])

    const emojiOptions = useMemo((): string[] => {
        const counts = new Map<string, number>()
        for (const { emoji } of annotations) {
            if (emoji) {
                counts.set(emoji, (counts.get(emoji) ?? 0) + 1)
            }
        }
        return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([emoji]) => emoji)
    }, [annotations])

    const setFilter = (patch: AnnotationsFilter): void => {
        const merged: AnnotationsFilter = { ...draft, ...patch }
        const emojis = merged.emojis?.length ? merged.emojis : undefined
        const search = merged.search?.trim() || undefined
        const next = emojis || search ? { emojis, search } : undefined
        setDraft(next)
        updateInsightFilter({ annotationsFilter: next })
    }

    const toggleEmoji = (emoji: string): void =>
        setFilter({
            emojis: selectedEmojis.includes(emoji)
                ? selectedEmojis.filter((e) => e !== emoji)
                : [...selectedEmojis, emoji],
        })

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <LemonCheckbox
                onChange={(value) => updateInsightFilter({ showAnnotations: value })}
                checked={enabled}
                label={<span className="font-normal">Show annotations</span>}
                size="small"
            />
            <LemonDropdown
                closeOnClickInside={false}
                placement="bottom-end"
                overlay={
                    <div className="flex flex-col gap-2 p-2 w-64">
                        {emojiOptions.length > 0 && (
                            <div className="flex flex-col gap-1">
                                <LemonLabel>Emoji</LemonLabel>
                                <div className="flex flex-wrap gap-1">
                                    {emojiOptions.map((emoji) => (
                                        <LemonButton
                                            key={emoji}
                                            size="small"
                                            type="secondary"
                                            active={selectedEmojis.includes(emoji)}
                                            onClick={() => toggleEmoji(emoji)}
                                            data-attr="insight-annotations-filter-emoji"
                                        >
                                            {emoji}
                                        </LemonButton>
                                    ))}
                                </div>
                            </div>
                        )}
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Text contains</LemonLabel>
                            <LemonInput
                                size="small"
                                value={searchDraft}
                                placeholder="Any text"
                                onChange={setSearchDraft}
                                onBlur={() => setFilter({ search: searchDraft })}
                                onPressEnter={() => setFilter({ search: searchDraft })}
                                data-attr="insight-annotations-filter-search"
                            />
                        </div>
                        {draft && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                onClick={() => setFilter({ emojis: undefined, search: undefined })}
                                data-attr="insight-annotations-filter-clear"
                            >
                                Show all annotations
                            </LemonButton>
                        )}
                    </div>
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    sideIcon={<IconChevronDown />}
                    disabledReason={!enabled ? 'Enable annotations to choose which ones to show' : undefined}
                    data-attr="insight-annotations-filter"
                >
                    {summarizeAnnotationsFilter(draft)}
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
