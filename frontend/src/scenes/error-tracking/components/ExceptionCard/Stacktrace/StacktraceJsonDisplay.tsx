import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { JSONViewer } from 'lib/components/JSONViewer'
import { useCallback } from 'react'

import { exceptionCardLogic } from '../exceptionCardLogic'
import { StacktraceBaseDisplayProps } from './StacktraceBase'

export function StacktraceJsonDisplay({
    className,
    renderLoading,
    renderEmpty,
}: StacktraceBaseDisplayProps): JSX.Element {
    const { properties, hasStacktrace } = useValues(errorPropertiesLogic)
    const { loading } = useValues(exceptionCardLogic)

    const renderExceptionHeader = useCallback((): JSX.Element => {
        return <Spinner />
    }, [])

    return (
        <div className={className}>
            {loading ? (
                renderLoading(renderExceptionHeader)
            ) : (
                <JSONViewer src={properties} name="event" collapsed={1} collapseStringsAfterLength={80} sortKeys />
            )}
            {!loading && !hasStacktrace && renderEmpty()}
        </div>
    )
}
