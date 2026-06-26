import type { ReactNode } from 'react'

import { LemonCheckbox, LemonInput, Link } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import type { UserBasicType } from '~/types'

export interface AlertingListToolbarProps {
    searchValue: string
    onSearchChange: (value: string) => void
    searchPlaceholder?: string
    feedbackLabel?: string
    onFeedbackClick?: () => void
    createdByValue?: string | number | null
    onCreatedByChange?: (user: UserBasicType | null) => void
    createdByLabel?: string
    showPaused?: boolean
    onShowPausedChange?: (checked: boolean | undefined) => void
    showPausedLabel?: string
    secondaryControls?: ReactNode
    extraControls?: ReactNode
}

export function AlertingListToolbar({
    searchValue,
    onSearchChange,
    searchPlaceholder = 'Search...',
    feedbackLabel = "Can't find what you're looking for?",
    onFeedbackClick,
    createdByValue = null,
    onCreatedByChange,
    createdByLabel = 'Created by:',
    showPaused = false,
    onShowPausedChange,
    showPausedLabel = 'Show paused',
    secondaryControls,
    extraControls,
}: AlertingListToolbarProps): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <LemonInput type="search" placeholder={searchPlaceholder} value={searchValue} onChange={onSearchChange} />
            {onFeedbackClick ? (
                <Link className="text-sm font-semibold" subtle onClick={onFeedbackClick}>
                    {feedbackLabel}
                </Link>
            ) : null}
            <div className="flex-1" />
            {onCreatedByChange ? (
                <div className="flex flex-col xl:flex-row items-center gap-0.5 xl:gap-2 shrink-0">
                    <span className="text-xs xl:text-sm">{createdByLabel}</span>
                    <MemberSelect value={createdByValue} onChange={onCreatedByChange} />
                </div>
            ) : null}
            {secondaryControls}
            {onShowPausedChange ? (
                <LemonCheckbox
                    label={showPausedLabel}
                    bordered
                    size="small"
                    checked={showPaused}
                    onChange={onShowPausedChange}
                />
            ) : null}
            {extraControls}
        </div>
    )
}
