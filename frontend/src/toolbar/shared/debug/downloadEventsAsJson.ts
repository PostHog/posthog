import { dayjs } from 'lib/dayjs'

export function downloadEventsAsJson(events: object[]): void {
    const json = JSON.stringify(events, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `posthog-events-${dayjs().format('YYYY-MM-DD-HHmmss')}.json`
    a.click()
    URL.revokeObjectURL(url)
}
