export class DeadlineSlots {
    private open = 0
    private waiters: (() => void)[] = []

    constructor(private readonly size: number) {}

    public async run(deadline: Promise<void>, work: () => Promise<void>): Promise<boolean> {
        if (this.open < this.size) {
            this.open++
        } else if (!(await this.waitForSlot(deadline))) {
            return false
        }
        try {
            await work()
            return true
        } finally {
            const next = this.waiters.shift()
            if (next) {
                next()
            } else {
                this.open--
            }
        }
    }

    private waitForSlot(deadline: Promise<void>): Promise<boolean> {
        return new Promise<boolean>((resolve) => {
            const waiter = (): void => resolve(true)
            this.waiters.push(waiter)
            void deadline.then(() => {
                const index = this.waiters.indexOf(waiter)
                if (index !== -1) {
                    this.waiters.splice(index, 1)
                    resolve(false)
                }
            })
        })
    }
}
