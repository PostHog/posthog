import { useActions, useValues } from 'kea'

import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { annotationsFilterLogic } from './annotationsFilterLogic'

export function AnnotationsFilterPopover(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filter, hiddenEmojis, searchValue, emojiOptions, showNoEmojiSwitch } = useValues(
        annotationsFilterLogic(insightProps)
    )
    const { setFilter, toggleEmoji, setSearchInput, commitSearch } = useActions(annotationsFilterLogic(insightProps))

    return (
        <div className="flex flex-col w-32">
            <div className="p-2">
                <LemonInput
                    size="small"
                    value={searchValue}
                    placeholder="Filter by text"
                    onChange={setSearchInput}
                    onBlur={() => commitSearch()}
                    onPressEnter={() => commitSearch()}
                    data-attr="insight-annotations-filter-search"
                />
            </div>
            {(emojiOptions.length > 0 || showNoEmojiSwitch) && (
                <div className="flex flex-col max-h-80 overflow-y-auto p-1 border-t">
                    {showNoEmojiSwitch && (
                        <LemonSwitch
                            fullWidth
                            label={<span className="text-xs font-normal leading-7">Default</span>}
                            className="px-2 [--lemon-switch-handle-size:15px]"
                            checked={!filter.hideWithoutEmoji}
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
    )
}
