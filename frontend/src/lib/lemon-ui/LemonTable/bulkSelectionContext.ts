import { createContext } from 'react'

import { UseBulkSelectionResult } from './useBulkSelection'

export const bulkSelectionContext = createContext<
    Pick<UseBulkSelectionResult<never>, 'selectedKeysSet' | 'isAllOnPageSelected' | 'isSomeOnPageSelected'>
>({ selectedKeysSet: new Set(), isAllOnPageSelected: false, isSomeOnPageSelected: false })
