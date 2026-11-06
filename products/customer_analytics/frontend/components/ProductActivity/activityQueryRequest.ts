import type { DisposablesManager } from 'kea-disposables'

import { uuid } from 'lib/utils/dom'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import type { DataNode, RefreshType } from '~/queries/schema/schema-general'

export class ActivityQueryRequest {
    private readonly controller = new AbortController()
    private readonly pending = new Set<string>()

    constructor(disposables: DisposablesManager, key: string, teamId: number | null) {
        disposables.add(
            () => () => {
                this.controller.abort()
                for (const queryId of this.pending) {
                    void cancelQueryOnServer(teamId, queryId)
                }
            },
            key,
            { pauseOnPageHidden: false }
        )
    }

    get signal(): AbortSignal {
        return this.controller.signal
    }

    throwIfAborted(): void {
        if (this.signal.aborted) {
            throw new DOMException('The query was canceled.', 'AbortError')
        }
    }

    async run<T>(execute: (signal: AbortSignal, queryId: string) => Promise<T>, queryId = uuid()): Promise<T> {
        this.throwIfAborted()
        this.pending.add(queryId)
        try {
            return await execute(this.signal, queryId)
        } finally {
            this.pending.delete(queryId)
        }
    }

    perform<N extends DataNode>(query: N, refresh?: RefreshType): Promise<NonNullable<N['response']>> {
        return this.run((signal, queryId) => performQuery(query, { signal }, refresh, queryId))
    }
}
