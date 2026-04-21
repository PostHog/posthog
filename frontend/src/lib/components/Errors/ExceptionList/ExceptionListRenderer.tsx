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
                <div key={exception.id}>
                    {index > 0 && (
                        <div className="flex items-center gap-2 my-2 ml-2 text-xs font-semibold text-muted uppercase tracking-wide">
                            <span>↳</span>
                            <span>Caused by</span>
                            <div className="flex-1 border-t border-dashed border-border" />
                        </div>
                    )}
                    <div className={cn(index > 0 && 'ml-4 pl-4 border-l-2 border-warning')}>
                        {renderException(exception, index)}
                    </div>
                </div>
            ))}
        </div>
    )
}
