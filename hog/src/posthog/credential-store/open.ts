import type { Runtime } from '@/core/runtime'

import { FileStore } from './file'
import { KeychainStore } from './keychain'
import type { StoreChoice } from './types'

export function openStore(runtime: Runtime, kind: StoreChoice): KeychainStore | FileStore {
    return kind === 'keychain' ? new KeychainStore(runtime) : new FileStore(runtime)
}
