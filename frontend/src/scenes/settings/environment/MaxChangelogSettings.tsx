import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { getTagProps } from 'scenes/max/components/MaxChangelog'
import { ChangelogEntry, maxChangelogLogic } from 'scenes/max/maxChangelogLogic'

export function MaxChangelogSettings(): JSX.Element {
    const { entries, isDismissed, hasEntries } = useValues(maxChangelogLogic)
    const { enableChangelog, dismissChangelog } = useActions(maxChangelogLogic)

    const handleToggle = (checked: boolean): void => {
        if (checked) {
            enableChangelog()
        } else {
            dismissChangelog()
        }
    }

    if (!hasEntries) {
        return (
            <div className="text-muted text-sm">
                No changelog entries available. Check back later for updates on new PostHog AI features.
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <LemonSwitch
                checked={!isDismissed}
                onChange={handleToggle}
                label="Show 'What's new' button in PostHog AI"
                bordered
            />

            <div>
                <h4 className="font-semibold text-sm mb-3">Recent updates</h4>
                <div className="space-y-2">
                    {entries.map((entry: ChangelogEntry, index: number) => (
                        <div key={index} className="flex gap-3 p-3 rounded-lg border bg-bg-light">
                            <div className="w-16 shrink-0 pt-0.5">
                                {entry.tag && <LemonTag size="small" {...getTagProps(entry.tag)} />}
                            </div>
                            <div className="flex-1 min-w-0">
                                <span className="font-medium text-sm">{entry.title}</span>
                                <p className="text-muted text-xs m-0">{entry.description}</p>
                            </div>
                        </div>
                    ))}
                </div>
                <p className="text-muted text-sm mt-3">
                    See the{' '}
                    <Link to="https://posthog.com/changelog?team=PostHog+AI" target="_blank">
                        complete changelog
                    </Link>{' '}
                    for all PostHog AI updates.
                </p>
            </div>
        </div>
    )
}
