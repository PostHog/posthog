import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconMagicWand, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { fixSQLErrorsLogic } from '../fixSQLErrorsLogic'
import { multitabEditorLogic } from '../multitabEditorLogic'

interface FixErrorButtonProps {
    type: LemonButtonProps['type']
    size?: LemonButtonProps['size']
    contentOverride?: string
    source: 'action-bar' | 'query-error'
}

export function FixErrorButton({ type, size, contentOverride, source }: FixErrorButtonProps): JSX.Element {
    const { queryInput, fixErrorsError, metadata } = useValues(multitabEditorLogic)
    const { fixErrors: fixHogQLErrors } = useActions(multitabEditorLogic)
    const { responseError } = useValues(dataNodeLogic)
    const { responseLoading: fixHogQLErrorsLoading } = useValues(fixSQLErrorsLogic)

    const queryError = responseError || metadata?.errors?.map((n) => n.message)?.join('. ') || undefined

    const icon = useMemo(() => {
        if (fixHogQLErrorsLoading) {
            return <Spinner />
        }

        if (fixErrorsError) {
            return <IconWarning className="text-warning" />
        }

        return <IconMagicWand />
    }, [fixHogQLErrorsLoading, fixErrorsError])

    const disabledReason = useMemo(() => {
        if (!queryError) {
            return 'No query error to fix'
        }

        if (fixErrorsError) {
            return fixErrorsError
        }

        return false
    }, [queryError, fixErrorsError])

    const content = useMemo(() => {
        if (fixHogQLErrorsLoading) {
            return 'Fixing...'
        }

        if (fixErrorsError) {
            return "Can't fix"
        }

        return contentOverride ?? 'Fix errors'
    }, [fixErrorsError, fixHogQLErrorsLoading, contentOverride])

    return (
        <LemonButton
            type={type}
            size={size}
            disabledReason={disabledReason}
            icon={icon}
            onClick={() => {
                fixHogQLErrors(queryInput ?? '', queryError)
                posthog.capture(`sql-editor-fix-error-click`, { source })
            }}
        >
            {content}
        </LemonButton>
    )
}
