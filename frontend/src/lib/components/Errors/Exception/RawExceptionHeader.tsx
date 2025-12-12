import { ErrorTrackingException } from '../types'
import { formatExceptionDisplay } from '../utils'

export function RawExceptionHeader({ exception }: { exception: ErrorTrackingException }): JSX.Element {
    return <p className="font-mono mb-0 font-bold line-clamp-1 mb-1">{formatExceptionDisplay(exception)}</p>
}
