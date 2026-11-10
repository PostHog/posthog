export class AcquisitionGate {
    private outstanding = 0
    private abandoned = 0
    private readonly waiting = new Set<() => void>()

    constructor(
        private readonly slots: number,
        private readonly name: string
    ) {}

    async acquire<T>(start: () => Promise<T>, deadlineAt: number, discardLate: (late: T) => unknown): Promise<T> {
        if (this.abandoned >= this.slots) {
            throw new Error(`${this.name}: ${this.abandoned} acquisitions passed their deadline and still wait`)
        }
        await this.takeSlot(deadlineAt)
        if (Date.now() >= deadlineAt) {
            this.freeSlot()
            throw new Error(`${this.name}: no acquisition slot came free before the deadline`)
        }

        let late = false
        return await new Promise<T>((resolve, reject) => {
            const timer = setTimeout(
                () => {
                    late = true
                    this.abandoned++
                    reject(new Error(`${this.name}: acquisition passed its deadline`))
                },
                Math.max(0, deadlineAt - Date.now())
            )
            new Promise<T>((started) => started(start()))
                .then(
                    (value) => {
                        clearTimeout(timer)
                        if (late) {
                            discardLate(value)
                        } else {
                            resolve(value)
                        }
                    },
                    (error) => {
                        clearTimeout(timer)
                        if (!late) {
                            reject(error)
                        }
                    }
                )
                .catch(() => undefined)
                .finally(() => {
                    if (late) {
                        this.abandoned--
                    }
                    this.freeSlot()
                })
        })
    }

    private takeSlot(deadlineAt: number): Promise<void> {
        if (this.outstanding < this.slots) {
            this.outstanding++
            return Promise.resolve()
        }
        return new Promise<void>((resolve, reject) => {
            const grant = (): void => {
                clearTimeout(timer)
                resolve()
            }
            const timer = setTimeout(
                () => {
                    this.waiting.delete(grant)
                    reject(new Error(`${this.name}: no acquisition slot came free before the deadline`))
                },
                Math.max(0, deadlineAt - Date.now())
            )
            this.waiting.add(grant)
        })
    }

    private freeSlot(): void {
        const next = this.waiting.values().next()
        if (next.done) {
            this.outstanding--
            return
        }
        this.waiting.delete(next.value)
        next.value()
    }
}
