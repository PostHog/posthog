import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { AnnotationsFilter } from '~/queries/schema/schema-general'
import { isAnnotationsFilterActive } from '~/queries/utils'

import { insightVizDataLogic } from '../insightVizDataLogic'

export function AnnotationsOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations, annotationsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { annotations } = useValues(annotationsModel)

    const enabled = showAnnotations !== false
    // updateInsightFilter debounces, so patches merge into a local draft to keep rapid emoji clicks.
    const [draft, setDraft] = useState(annotationsFilter ?? undefined)
    useEffect(() => setDraft(annotationsFilter ?? undefined), [annotationsFilter])
    const hiddenEmojis = draft?.hiddenEmojis ?? []
    const [searchDraft, setSearchDraft] = useState(draft?.search ?? '')
    useEffect(() => setSearchDraft(draft?.search ?? ''), [draft?.search])

    const emojiOptions = useMemo((): string[] => {
        const counts = new Map<string, number>()
        for (const { emoji } of annotations) {
            if (emoji) {
                counts.set(emoji, (counts.get(emoji) ?? 0) + 1)
            }
        }
        const loaded = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([emoji]) => emoji)
        // Keep switches for hidden emojis that no loaded annotation uses, so the user can still clear them.
        const stale = hiddenEmojis.filter((emoji) => !counts.has(emoji))
        return [...loaded, ...stale]
    }, [annotations, hiddenEmojis])

    const hasAnnotationsWithoutEmoji = useMemo(() => annotations.some(({ emoji }) => !emoji), [annotations])
    const showNoEmojiSwitch = hasAnnotationsWithoutEmoji || !!draft?.hideWithoutEmoji

    const setFilter = (patch: AnnotationsFilter): void => {
        const merged: AnnotationsFilter = { ...draft, ...patch }
        const hiddenEmojis = merged.hiddenEmojis?.length ? merged.hiddenEmojis : undefined
        const hideWithoutEmoji = merged.hideWithoutEmoji || undefined
        const search = merged.search?.trim() || undefined
        const next = hiddenEmojis || hideWithoutEmoji || search ? { hiddenEmojis, hideWithoutEmoji, search } : undefined
        setDraft(next)
        updateInsightFilter({ annotationsFilter: next })
    }

    const toggleEmoji = (emoji: string, shown: boolean): void =>
        setFilter({
            hiddenEmojis: shown ? hiddenEmojis.filter((e) => e !== emoji) : [...hiddenEmojis, emoji],
        })

    const isFilterActive = isAnnotationsFilterActive(draft)

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
                    <div className="flex flex-col w-32">
                        <div className="p-2">
                            <LemonInput
                                size="small"
                                value={searchDraft}
                                placeholder="Filter by text"
                                onChange={setSearchDraft}
                                onBlur={() => setFilter({ search: searchDraft })}
                                onPressEnter={() => setFilter({ search: searchDraft })}
                                data-attr="insight-annotations-filter-search"
                            />
                        </div>
                        {(emojiOptions.length > 0 || showNoEmojiSwitch) && (
                            <div className="flex flex-col max-h-80 overflow-y-auto p-1 border-t">
                                {showNoEmojiSwitch && (
                                    <LemonSwitch
                                        fullWidth
                                        label={<span className="text-xs font-normal leading-7">No emoji</span>}
                                        className="px-2 [--lemon-switch-handle-size:15px]"
                                        checked={!draft?.hideWithoutEmoji}
                                        onChange={(shown) => setFilter({ hideWithoutEmoji: !shown })}
                                        data-attr="insight-annotations-filter-no-emoji"
                                    />
                                )}
                                {emojiOptions.map((emoji) => (
                                    <LemonSwitch
                                        key={emoji}
                                        fullWidth
                                        label={<span className="text-lg leading-7">{emoji}</span>}
                                        className="px-2 [--lemon-switch-handle-size:15px]"
                                        checked={!hiddenEmojis.includes(emoji)}
                                        onChange={(shown) => toggleEmoji(emoji, shown)}
                                        data-attr="insight-annotations-filter-emoji"
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    active={isFilterActive}
                    disabledReason={enabled ? undefined : 'Turn on annotations to filter them'}
                    data-attr="insight-annotations-filter-button"
                >
                    Filters
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
