import { SesMessage } from './ses'

export const TRUTH_PAGE_LIMIT = 1000

export type TruthRecord = {
    seq: number
    at: string
    kind: 'ses.send'
    unitId?: string
    actionId?: string
    status: number
    fault?: string
    detail: { message?: SesMessage; error?: string }
}

export type TruthPage = { records: TruthRecord[]; next: number }

export class Truth {
    readonly records: TruthRecord[] = []

    append(record: Omit<TruthRecord, 'seq' | 'at'>): TruthRecord {
        const appended = { seq: this.records.length + 1, at: new Date().toISOString(), ...record }
        this.records.push(appended)
        return appended
    }

    page(after: number, limit: number): TruthPage {
        const records = this.records.slice(after, after + Math.min(limit, TRUTH_PAGE_LIMIT))
        return { records, next: records.at(-1)?.seq ?? after }
    }
}
