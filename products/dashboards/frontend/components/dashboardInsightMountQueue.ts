type MountRequest = { mount: () => void; cancelled: boolean }

// A shared queue prevents a fast scroll from mounting all newly visible insight cards in one frame.
const pending: MountRequest[] = []
let scheduled = false

function processNextMount(): void {
    scheduled = false
    let request = pending.shift()
    while (request?.cancelled) {
        request = pending.shift()
    }
    request?.mount()
    if (pending.length > 0) {
        scheduleNextMount()
    }
}

function scheduleNextMount(): void {
    if (!scheduled) {
        scheduled = true
        requestAnimationFrame(processNextMount)
    }
}

export function queueDashboardInsightMount(mount: () => void): () => void {
    const request = { mount, cancelled: false }
    pending.push(request)
    scheduleNextMount()
    return () => {
        request.cancelled = true
    }
}
