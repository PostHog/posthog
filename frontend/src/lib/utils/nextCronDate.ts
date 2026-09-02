import { CronExpressionParser } from 'cron-parser'

export function nextCronDate(expression: string, currentDate: Date, timezone?: string): Date | null {
    try {
        return CronExpressionParser.parse(expression, { currentDate, tz: timezone }).next().toDate()
    } catch {
        return null
    }
}
