import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { ChangelogEntry, maxChangelogLogic } from '../maxChangelogLogic'

export function getTagProps(tag: ChangelogEntry['tag']): {
    type: 'highlight' | 'warning' | 'completion'
    children: string
} {
    switch (tag) {
        case 'new':
            return { type: 'highlight', children: 'NEW' }
        case 'improved':
            return { type: 'completion', children: 'IMPROVED' }
        case 'beta':
            return { type: 'warning', children: 'BETA' }
        default:
            return { type: 'highlight', children: 'NEW' }
    }
}

export function MaxChangelog(): JSX.Element | null {
    const flagEnabled = useFeatureFlag('POSTHOG_AI_CHANGELOG')
    const { entries, isOpen, hasUnread, isVisible } = useValues(maxChangelogLogic)
    const { openChangelog, closeChangelog, dismissChangelog } = useActions(maxChangelogLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
    const displayedEntries = useMemo(() => entries.slice(0, 4), [entries])
    const hasMoreEntries = entries.length > 4

    if (!flagEnabled || !isVisible) {
        return null
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={closeChangelog}
            placement="bottom"
            className="max-w-sm"
            overlay={
                <div className="p-3 min-w-[280px] max-w-[320px]">
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="font-semibold text-sm m-0">What's new in PostHog AI</h3>
                        <LemonButton size="xsmall" icon={<IconX />} onClick={closeChangelog} />
                    </div>
                    <ul className="space-y-3 mb-3">
                        {displayedEntries.map((entry, index) => (
                            <li key={index} className="flex gap-2 text-sm">
                                <div className="w-16 shrink-0 pt-0.5">
                                    {entry.tag && <LemonTag size="small" {...getTagProps(entry.tag)} />}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <span className="font-medium">{entry.title}</span>
                                    <p className="text-muted text-xs m-0">{entry.description}</p>
                                </div>
                            </li>
                        ))}
                    </ul>
                    <div className="flex justify-between items-center pt-2 border-t">
                        {hasMoreEntries ? (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => {
                                    closeChangelog()
                                    openSettingsPanel({ sectionId: 'environment-max' })
                                }}
                            >
                                Show all
                            </LemonButton>
                        ) : (
                            <span />
                        )}
                        <LemonButton size="xsmall" type="tertiary" onClick={dismissChangelog}>
                            Don't show again
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconSparkles />}
                onClick={isOpen ? closeChangelog : openChangelog}
                className="relative"
            >
                What's new
                {hasUnread && <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-danger rounded-full" />}
            </LemonButton>
        </Popover>
    )
}
