export async function settleAllThenThrowFirst(work: Promise<unknown>[]): Promise<void> {
    const failed = (await Promise.allSettled(work)).find(
        (outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected'
    )
    if (failed) {
        throw failed.reason
    }
}
