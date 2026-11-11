import { useActions } from 'kea'
import type { ReactNode } from 'react'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { KeyClauseApi, KeyClauseRoleEnumApi } from 'products/today/frontend/generated/api.schemas'

import { TodayHoverMark } from './TodayHoverMark'
import { todayReportLogic } from './todayReportLogic'

const ROLE_LABEL: Record<KeyClauseRoleEnumApi, string> = {
    problem: 'The problem',
    cause: 'The cause',
    fix: 'The fix',
}

export function TodayKeyClauseMark({
    keyClause,
    reportId,
    children,
}: {
    keyClause: KeyClauseApi
    reportId: string
    children: ReactNode
}): JSX.Element {
    const { markOpened } = useActions(todayReportLogic({ reportId }))
    return (
        <TodayHoverMark
            className="TodayKeyClauseMark"
            dataAttr={`today-report-key-${keyClause.role}`}
            onOpen={() => markOpened('key_clause')}
            card={
                <div className="flex flex-col gap-2 p-3">
                    <Text size="xs" variant="muted" render={<div />} className="flex items-center gap-1.5">
                        <IconSparkles className="size-3.5" aria-hidden />
                        <span className="font-medium text-foreground">{ROLE_LABEL[keyClause.role]}</span>
                        <span aria-hidden>·</span>
                        <span>AI picked this because the full report explains it further</span>
                    </Text>
                    <Text
                        size="sm"
                        render={<blockquote />}
                        className="m-0 flex flex-col gap-1.5 border-l-2 border-solid ps-3 text-pretty text-foreground"
                    >
                        {keyClause.expansion.map((sentence) => (
                            <span key={sentence}>{sentence}</span>
                        ))}
                    </Text>
                    <Button
                        variant="link"
                        size="sm"
                        className="self-start px-0"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.inboxReport('reports', reportId)} />}
                        data-attr="today-report-key-full-report"
                    >
                        Open the full report
                        <IconArrowRight />
                    </Button>
                </div>
            }
        >
            {children}
        </TodayHoverMark>
    )
}
