// The use-sync-external-store shim returns React's own hook on React 18 and newer. This module
// does the same as ESM, so the bundle does not need a CommonJS require() of react.
import * as React from 'react'

export const useSyncExternalStore = React.useSyncExternalStore
