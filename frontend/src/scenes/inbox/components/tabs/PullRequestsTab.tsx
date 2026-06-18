import { useState } from 'react'

import { IconBolt, IconPullRequest } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { INBOX_FLAT_TAB_LIST_PARAMS } from '../../logics/reportListLogic'
import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'
import { RapidReview } from '../RapidReview'

export function PullRequestsTab(): JSX.Element {
    const [rapidReview, setRapidReview] = useState(false)

    if (rapidReview) {
        return <RapidReview onExit={() => setRapidReview(false)} />
    }

    return (
        <InboxReportList
            tabKey="pulls"
            listParams={INBOX_FLAT_TAB_LIST_PARAMS.pulls}
            Card={ReportCard}
            headerActions={
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconBolt />}
                    tooltip="Rapid review"
                    aria-label="Rapid review"
                    onClick={() => setRapidReview(true)}
                    className="bg-surface-primary"
                />
            }
            emptyState={{
                icon: <IconPullRequest className="text-2xl" />,
                title: 'No pull requests right now',
                description:
                    'When an agent ships a code change, the PR draft lands here for you to review and publish.',
            }}
        />
    )
}
