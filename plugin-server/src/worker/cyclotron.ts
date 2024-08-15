// We use a dynamic `require` here because `import` (at least in VS Code) doesn't seem to understand
// or find the Node C module.
const cyclotron = require('cyclotron')

export function hello() {
    return cyclotron.hello('hello, world')
}

interface PoolConfig {
    dbUrl: string
    maxConnections?: number
    minConnections?: number
    acquireTimeoutSeconds?: number
    maxLifetimeSeconds?: number
    idleTimeoutSeconds?: number
}

// Type as expected by Cyclotron.
interface InternalPoolConfig {
    db_url: string
    max_connections?: number
    min_connections?: number
    acquire_timeout_seconds?: number
    max_lifetime_seconds?: number
    idle_timeout_seconds?: number
}

interface ManagerConfig {
    shards: PoolConfig[]
}

// Type as expected by Cyclotron.
interface InternalManagerConfig {
    shards: InternalPoolConfig[]
}

interface JobInit {
    teamId: number
    functionId: string
    queueName: string
    priority?: number
    scheduled?: Date
    vmState?: string
    parameters?: string
    metadata?: string
}

// Type as expected by Cyclotron.
interface InternalJobInit {
    team_id: number
    function_id: string
    queue_name: string
    priority?: number
    scheduled?: Date
    vm_state?: string
    parameters?: string
    metadata?: string
}

type JobState = 'available' | 'running' | 'completed' | 'failed' | 'paused'

interface Job {
    id: string
    teamId: number
    functionId: string | null
    created: Date
    lockId: string | null
    lastHeartbeat: Date | null
    janitorTouchCount: number
    transitionCount: number
    lastTransition: Date
    queueName: string
    state: JobState
    priority: number
    scheduled: Date
    vmState: string | null
    metadata: string | null
    parameters: string | null
}

// Type as returned by Cyclotron.
interface InternalJob {
    id: string
    team_id: number
    function_id: string | null
    created: string
    lock_id: string | null
    last_heartbeat: string | null
    janitor_touch_count: number
    transition_count: number
    last_transition: string
    queue_name: string
    state: JobState
    priority: number
    scheduled: string
    vm_state: string | null
    metadata: string | null
    parameters: string | null
}

export async function initWorker(poolConfig: PoolConfig) {
    const initWorkerInternal: InternalPoolConfig = {
        db_url: poolConfig.dbUrl,
        max_connections: poolConfig.maxConnections,
        min_connections: poolConfig.minConnections,
        acquire_timeout_seconds: poolConfig.acquireTimeoutSeconds,
        max_lifetime_seconds: poolConfig.maxLifetimeSeconds,
        idle_timeout_seconds: poolConfig.idleTimeoutSeconds,
    }
    return await cyclotron.initWorker(JSON.stringify(initWorkerInternal))
}

export async function initManager(managerConfig: ManagerConfig) {
    const managerConfigInternal: InternalManagerConfig = {
        shards: managerConfig.shards.map((shard) => ({
            db_url: shard.dbUrl,
            max_connections: shard.maxConnections,
            min_connections: shard.minConnections,
            acquire_timeout_seconds: shard.acquireTimeoutSeconds,
            max_lifetime_seconds: shard.maxLifetimeSeconds,
            idle_timeout_seconds: shard.idleTimeoutSeconds,
        })),
    }
    return await cyclotron.initManager(JSON.stringify(managerConfigInternal))
}

export async function maybeInitWorker(poolConfig: PoolConfig) {
    const initWorkerInternal: InternalPoolConfig = {
        db_url: poolConfig.dbUrl,
        max_connections: poolConfig.maxConnections,
        min_connections: poolConfig.minConnections,
        acquire_timeout_seconds: poolConfig.acquireTimeoutSeconds,
        max_lifetime_seconds: poolConfig.maxLifetimeSeconds,
        idle_timeout_seconds: poolConfig.idleTimeoutSeconds,
    }
    return await cyclotron.maybeInitWorker(JSON.stringify(initWorkerInternal))
}

export async function maybeInitManager(managerConfig: ManagerConfig) {
    const managerConfigInternal: InternalManagerConfig = {
        shards: managerConfig.shards.map((shard) => ({
            db_url: shard.dbUrl,
            max_connections: shard.maxConnections,
            min_connections: shard.minConnections,
            acquire_timeout_seconds: shard.acquireTimeoutSeconds,
            max_lifetime_seconds: shard.maxLifetimeSeconds,
            idle_timeout_seconds: shard.idleTimeoutSeconds,
        })),
    }
    return await cyclotron.maybeInitManager(JSON.stringify(managerConfigInternal))
}

export async function createJob(job: JobInit) {
    job.priority ??= 1
    job.scheduled ??= new Date()

    const jobInitInternal: InternalJobInit = {
        team_id: job.teamId,
        function_id: job.functionId,
        queue_name: job.queueName,
        priority: job.priority,
        scheduled: job.scheduled,
        vm_state: job.vmState,
        parameters: job.parameters,
        metadata: job.metadata,
    }
    return await cyclotron.createJob(JSON.stringify(jobInitInternal))
}

function convertInternalJobToJob(jobInternal: InternalJob): Job {
    return {
        id: jobInternal.id,
        teamId: jobInternal.team_id,
        functionId: jobInternal.function_id,
        created: new Date(jobInternal.created),
        lockId: jobInternal.lock_id,
        lastHeartbeat: jobInternal.last_heartbeat ? new Date(jobInternal.last_heartbeat) : null,
        janitorTouchCount: jobInternal.janitor_touch_count,
        transitionCount: jobInternal.transition_count,
        lastTransition: new Date(jobInternal.last_transition),
        queueName: jobInternal.queue_name,
        state: jobInternal.state,
        priority: jobInternal.priority,
        scheduled: new Date(jobInternal.scheduled),
        vmState: jobInternal.vm_state,
        metadata: jobInternal.metadata,
        parameters: jobInternal.parameters,
    }
}

export async function dequeueJobs(queueName: string, limit: number): Promise<Job[]> {
    const jobsStr = await cyclotron.dequeueJobs(queueName, limit)
    const jobs: InternalJob[] = JSON.parse(jobsStr)
    return jobs.map(convertInternalJobToJob)
}
export async function dequeueJobsWithVmState(queueName: string, limit: number): Promise<Job[]> {
    const jobsStr = await cyclotron.dequeueJobsWithVmState(queueName, limit)
    const jobs: InternalJob[] = JSON.parse(jobsStr)
    return jobs.map(convertInternalJobToJob)
}

export async function flushJob(jobId: string) {
    return await cyclotron.flushJob(jobId)
}

export function setState(jobId: string, jobState: JobState) {
    return cyclotron.setState(jobId, jobState)
}

export function setQueue(jobId: string, queueName: string) {
    return cyclotron.setQueue(jobId, queueName)
}

export function setPriority(jobId: string, priority: number) {
    return cyclotron.setPriority(jobId, priority)
}

export function setScheduledAt(jobId: string, scheduledAt: Date) {
    return cyclotron.setScheduledAt(jobId, scheduledAt.toISOString())
}

function serializeObject(name: string, obj: Record<string, any> | null): string | null {
    if (obj === null) {
        return null
    } else if (typeof obj === 'object' && obj !== null) {
        return JSON.stringify(obj)
    } else {
        throw new Error(`${name} must be either an object or null`)
    }
}

export function setVmState(jobId: string, vmState: Record<string, any> | null) {
    const serialized = serializeObject('vmState', vmState)
    return cyclotron.setVmState(jobId, serialized)
}

export function setMetadata(jobId: string, metadata: Record<string, any> | null) {
    const serialized = serializeObject('metadata', metadata)
    return cyclotron.setMetadata(jobId, serialized)
}

export function setParameters(jobId: string, parameters: Record<string, any> | null) {
    const serialized = serializeObject('parameters', parameters)
    return cyclotron.setParameters(jobId, serialized)
}
