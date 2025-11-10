declare global {
    interface Scheduler {
        postTask<T>(callback: () => T, options?: { priority?: 'user-visible' }): Promise<T>
    }

    interface Window {
        scheduler?: Scheduler
    }
}

export async function yieldToMain(): Promise<void> {
    if ('scheduler' in window && window.scheduler?.postTask) {
        await window.scheduler.postTask(() => {}, { priority: 'user-visible' })
    } else {
        await new Promise((resolve) => setTimeout(resolve, 0))
    }
}
