import type { TraceCellLoad } from '../shared/cellLoads'
import type { ErrorFirstSeen } from './errorFirstSeenLogic'

/** New comes with the error's first seen, so an error shows no New tag until that read lands, or after it fails. */
export function isNewError(load: TraceCellLoad<ErrorFirstSeen> | undefined): boolean {
    return load?.status === 'ready' && load.value.isNew
}
