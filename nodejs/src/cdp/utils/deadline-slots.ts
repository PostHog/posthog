// At most `size` calls run at once. A caller that finds every slot taken waits, holding nothing, and gives up
// when its deadline settles first. A running call keeps its slot until it settles, even past its deadline,
// because nothing can cancel it; a freed slot goes straight to the next waiter.
export class DeadlineSlots {
    private open = 0
    private waiters: (() => void)[] = []

    constructor(private readonly size: number) {}

    // Resolves true once `work` ran, or false without running it when `deadline` settled before a slot freed.
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
