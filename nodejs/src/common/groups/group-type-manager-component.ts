import { TeamManager } from '~/common/utils/team-manager'
import { Component } from '~/ingestion/common/scopes'

import { GroupTypeManager } from './group-type-manager'
import { GroupRepository } from './repositories/group-repository.interface'

/**
 * Scope owner for the `GroupTypeManager`. Like the schema-enforcement manager it
 * holds only an in-memory `LazyLoader` cache over the shared group repository and
 * team manager (neither of which it owns), so `start()` constructs it and `stop()`
 * is a no-op. Owning it in the shared scope shares one warm cache across the
 * combined-mode analytics lanes rather than building one per lane.
 */
export class GroupTypeManagerComponent implements Component<GroupTypeManager> {
    constructor(
        private readonly groupRepository: GroupRepository,
        private readonly teamManager: TeamManager
    ) {}

    start(): Promise<{ value: GroupTypeManager; stop: () => Promise<void> }> {
        return Promise.resolve({
            value: new GroupTypeManager(this.groupRepository, this.teamManager),
            stop: () => Promise.resolve(),
        })
    }
}
