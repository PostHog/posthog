import { useMountedLogic } from 'kea'

import { osFrameBridgeLogic } from './osFrameBridgeLogic'

/** Connects an app inside an OS window to the OS. Render it only in framed mode. */
export function OsFrameBridge(): null {
    useMountedLogic(osFrameBridgeLogic)
    return null
}
