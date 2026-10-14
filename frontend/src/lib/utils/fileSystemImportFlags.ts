import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { FileSystemImport } from '~/queries/schema/schema-general'

/** Whether a navigation item's feature flag gate is open. An item with no flag is always shown. */
export function isFileSystemImportFlagEnabled(
    item: Pick<FileSystemImport, 'flag' | 'alternativeFlags'>,
    featureFlags: FeatureFlagsSet
): boolean {
    if (!item.flag) {
        return true
    }
    const flags = featureFlags as Record<string, boolean | string | undefined>
    return [item.flag, ...(item.alternativeFlags ?? [])].some((flag) => !!flags[flag])
}
