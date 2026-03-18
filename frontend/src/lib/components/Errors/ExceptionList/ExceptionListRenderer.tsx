import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingExceptionList } from '../types'

type ExceptionListRendererProps = {
    className?: string
    exceptionList: ErrorTrackingExceptionList
    renderException: (exception: ErrorTrackingExceptionList[number], index: number) => React.ReactNode
}

export function ExceptionListRenderer({
    className,
    exceptionList,
    renderException,
}: ExceptionListRendererProps): JSX.Element {
    return (
        <div className={cn('space-y-2', className)}>
            {exceptionList.map((exception, index) => (
                <div key={exception.id}>{renderException(exception, index)}</div>
            ))}
        </div>
    )
}
