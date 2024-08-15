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

interface InitWorkerInternal {
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

interface JobInitInternal {
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

export async function initWorker(poolConfig: PoolConfig) {
    const initWorkerInternal: InitWorkerInternal = {
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
    return await cyclotron.initManager(JSON.stringify({ ...managerConfig }))
}

export async function maybeInitWorker(poolConfig: PoolConfig) {
    return await cyclotron.maybeInitWorker(JSON.stringify({ ...poolConfig }))
}

export async function maybeInitManager(managerConfig: ManagerConfig) {
    return await cyclotron.maybeInitManager(JSON.stringify({ ...managerConfig }))
}

export async function createJob(job: JobInit) {
    job.priority ??= 1
    job.scheduled ??= new Date()

    const jobInitInternal: JobInitInternal = {
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

export async function dequeueJobs(queueName: string, limit: number) {
    return await cyclotron.dequeueJobs(queueName, limit)
}

export async function dequeueWithVmState(queueName: string, limit: number) {
    return await cyclotron.dequeueWithVmState(queueName, limit)
}

export async function flushJob(jobId: string) {
    return await cyclotron.flushJob(jobId)
}

export async function setState(jobId: string, jobState: JobState) {
    return await cyclotron.setState(jobId, jobState)
}

export async function setQueue(jobId: string, queueName: string) {
    return await cyclotron.setQueue(jobId, queueName)
}

export async function setPriority(jobId: string, priority: number) {
    return await cyclotron.setPriority(jobId, priority)
}

export async function setScheduledAt(jobId: string, scheduledAt: Date) {
    return await cyclotron.setScheduledAt(jobId, scheduledAt.toISOString())
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

export async function setVmState(jobId: string, vmState: Record<string, any> | null) {
    const serialized = serializeObject('vmState', vmState)
    return await cyclotron.setVmState(jobId, serialized)
}

export async function setMetadata(jobId: string, metadata: Record<string, any> | null) {
    const serialized = serializeObject('metadata', metadata)
    return await cyclotron.setMetadata(jobId, serialized)
}

export async function setParameters(jobId: string, parameters: Record<string, any> | null) {
    const serialized = serializeObject('parameters', parameters)
    return await cyclotron.setParameters(jobId, serialized)
}
