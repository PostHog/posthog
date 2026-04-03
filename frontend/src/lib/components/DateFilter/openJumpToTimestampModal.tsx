import { combineUrl, router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

import { JumpToTimestampForm } from './JumpToTimestampForm'

export function openJumpToTimestampModal(): void {
    LemonDialog.open({
        title: 'Jump to timestamp',
        content: (closeDialog) => <JumpToTimestampModalContent onClose={closeDialog} />,
        primaryButton: null,
        className: '!m-auto',
    })
}

function JumpToTimestampModalContent({ onClose }: { onClose: () => void }): JSX.Element {
    const handleSubmit = (dateFrom: string, dateTo: string): void => {
        const baseQuery = getDefaultEventsSceneQuery()
        const query = {
            ...baseQuery,
            source: { ...baseQuery.source, after: dateFrom, before: dateTo },
        }
        const url = combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url
        onClose()
        router.actions.push(url)
    }

    return (
        <JumpToTimestampForm onSubmit={handleSubmit}>
            {({ dateRange, submit }) => (
                <>
                    <p className="text-secondary text-sm mb-0 mt-4">
                        Enter a timestamp to explore events filtered to a time window around it.
                    </p>
                    <div className="flex justify-end mt-4">
                        <LemonButton
                            size="small"
                            type="primary"
                            disabledReason={!dateRange ? 'Enter a valid timestamp' : undefined}
                            onClick={submit}
                            data-attr="jump-to-timestamp-apply"
                        >
                            Go to events
                        </LemonButton>
                    </div>
                </>
            )}
        </JumpToTimestampForm>
    )
}
