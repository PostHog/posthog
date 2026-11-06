/** Counts what is in use, in total and per team. A caller over either limit gets a refusal instead of a place in line. */
export class TeamLimit {
    private used = 0
    private readonly usedByTeam = new Map<number, number>()

    constructor(
        private readonly total: number,
        private readonly perTeam: number
    ) {}

    public get inUse(): number {
        return this.used
    }

    public tryTake(teamId: number, amount: number): boolean {
        const teamUsed = this.usedByTeam.get(teamId) ?? 0
        if (this.used + amount > this.total || teamUsed + amount > this.perTeam) {
            return false
        }
        this.used += amount
        this.usedByTeam.set(teamId, teamUsed + amount)
        return true
    }

    public give(teamId: number, amount: number): void {
        this.used -= amount
        const teamUsed = (this.usedByTeam.get(teamId) ?? 0) - amount
        if (teamUsed <= 0) {
            this.usedByTeam.delete(teamId)
        } else {
            this.usedByTeam.set(teamId, teamUsed)
        }
    }
}
