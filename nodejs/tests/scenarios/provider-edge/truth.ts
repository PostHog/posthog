import { createHash } from 'crypto'

import { SesAttachment, SesMessage } from './ses'

export const TRUTH_PAGE_LIMIT = 1000

export type TruthAttachment = Omit<SesAttachment, 'bytes'> & { size: number; sha256: string }

export type TruthMessage = Omit<SesMessage, 'attachments'> & { attachments: TruthAttachment[] }

export type TruthRecord = {
    seq: number
    at: string
    kind: 'ses.send' | 'webhook'
    unitId?: string
    actionId?: string
    status: number
    fault?: string
    detail: {
        message?: TruthMessage
        error?: string
        errorType?: string
        request?: { method: string; host: string; path: string }
    }
}

export type TruthPage = { records: TruthRecord[]; next: number }

export type TruthHead = { head: number }

export function truthMessageOf({ attachments, ...message }: SesMessage): TruthMessage {
    return {
        ...message,
        attachments: attachments.map(({ bytes, ...attachment }) => ({
            ...attachment,
            size: bytes.length,
            sha256: createHash('sha256').update(bytes).digest('hex'),
        })),
    }
}

export class Truth {
    readonly records: TruthRecord[] = []

    append(record: Omit<TruthRecord, 'seq' | 'at'>): TruthRecord {
        const appended = { seq: this.records.length + 1, at: new Date().toISOString(), ...record }
        this.records.push(appended)
        return appended
    }

    head(): TruthHead {
        return { head: this.records.at(-1)?.seq ?? 0 }
    }

    page(after: number, limit: number): TruthPage {
        const records = this.records.slice(after, after + Math.min(limit, TRUTH_PAGE_LIMIT))
        return { records, next: records.at(-1)?.seq ?? after }
    }
}
