import { z } from 'zod'

export type MetricPoint = { at: number; value: number }

export type SeriesRequest = { ids: string[]; from: number; to: number; subject: (id: string) => string }

const Answer = z
    .object({
        MetricDataResults: z.array(
            z
                .object({
                    Id: z.string(),
                    StatusCode: z.unknown(),
                    Messages: z.array(z.object({ Code: z.unknown(), Value: z.unknown() }).loose()).optional(),
                    Timestamps: z.array(z.unknown()).default([]),
                    Values: z.array(z.unknown()).default([]),
                })
                .loose()
        ),
        NextToken: z.unknown(),
    })
    .loose()

const IsoTime = z.iso.datetime({ offset: true })

const iso = (at: number): string => new Date(at).toISOString()

export function seriesOf(answer: unknown, { ids, from, to, subject }: SeriesRequest): Record<string, MetricPoint[]> {
    const parsed = Answer.safeParse(answer)
    if (!parsed.success) {
        throw new Error(`CloudWatch answered in a shape that is not GetMetricData: ${z.prettifyError(parsed.error)}`)
    }
    const { MetricDataResults, NextToken } = parsed.data
    if (NextToken !== undefined) {
        throw new Error('CloudWatch answered with a NextToken, so the answer is only one page')
    }
    const answered = MetricDataResults.map(({ Id }) => Id)
    if (answered.length !== ids.length || ids.some((id) => answered.filter((name) => name === id).length !== 1)) {
        throw new Error(`CloudWatch answered the series ${answered.join(', ') || 'none'}, not ${ids.join(', ')}`)
    }
    return Object.fromEntries(
        MetricDataResults.map(({ Id, StatusCode, Messages = [], Timestamps, Values }) => {
            const fail = (problem: string): never => {
                throw new Error(`${subject(Id)} ${problem}`)
            }
            if (StatusCode !== 'Complete') {
                const said = Messages.map(({ Code, Value }) => String(Value ?? Code))
                fail(
                    [
                        `came back ${StatusCode === undefined ? 'with no status' : String(StatusCode)}, not Complete`,
                        ...said,
                    ].join(': ')
                )
            }
            if (Timestamps.length !== Values.length) {
                fail(`has ${Timestamps.length} timestamps and ${Values.length} values`)
            }
            const unreadable = Timestamps.filter((_, i) => !Number.isFinite(Values[i]))
            if (unreadable.length > 0) {
                fail(`has a value that is not a finite number at ${unreadable.map(String).join(', ')}`)
            }
            const untimed = Timestamps.filter((at) => !IsoTime.safeParse(at).success)
            if (untimed.length > 0) {
                fail(`has a timestamp that is not a time: ${untimed.map(String).join(', ')}`)
            }
            const points = Timestamps.map((at, i) => ({ at: Date.parse(at as string), value: Values[i] as number }))
            const outside = points.filter(({ at }) => at < from || at >= to)
            if (outside.length > 0) {
                fail(
                    `has a timestamp outside the ${iso(from)} to ${iso(to)} it asked for: ${outside.map(({ at }) => iso(at)).join(', ')}`
                )
            }
            const unordered = points.filter(({ at }, i) => i > 0 && at <= points[i - 1].at)
            if (unordered.length > 0) {
                fail(`is not in ascending time order at ${unordered.map(({ at }) => iso(at)).join(', ')}`)
            }
            return [Id, points]
        })
    )
}
