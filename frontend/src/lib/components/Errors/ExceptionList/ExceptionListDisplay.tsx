import { cn } from 'lib/utils/css-classes'

import { ErrorTrackingExceptionList } from '../types'

type ExceptionListDisplayProps = {
    className?: string
    exceptionList: ErrorTrackingExceptionList
    renderException: (exception: ErrorTrackingExceptionList[number]) => React.ReactNode
}

export function ExceptionListDisplay({
    className,
    exceptionList,
    renderException,
}: ExceptionListDisplayProps): JSX.Element {
    return (
        <div className={cn('space-y-2 mb-2', className)}>
            {exceptionList.map((exception) => (
                <div key={exception.id}>{renderException(exception)}</div>
            ))}
        </div>
    )
}
