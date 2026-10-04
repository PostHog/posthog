import { Dayjs, dayjs } from 'lib/dayjs'

import type { SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { shortDate } from './todayProse'

export interface TodayQuotedText {
    excerpt: string
    values?: string[]
}

export type TodayFigureCardContent =
    | ({
          kind: 'signal'
          signal: SignalViewApi
          working?: { expression: string; result: string }
      } & TodayQuotedText)
    | {
          kind: 'metric'
          total: string
          at: string | null
          range: { from: string; to: string } | null
          caption: string | null
          window: string | null
          trend: number[] | null
          chartType: 'bar' | 'line'
          link: { url: string; label: string } | null
      }
    | { kind: 'none' }

function daysAgo(date: string, now: Dayjs = dayjs()): number {
    return now.startOf('day').diff(dayjs(date).startOf('day'), 'day')
}

export function anchorToday(text: string, date: string, now: Dayjs = dayjs()): string {
    return daysAgo(date, now) > 0 ? text.replace(/\btoday\b/gi, (word) => `${word} [${shortDate(date)}]`) : text
}
