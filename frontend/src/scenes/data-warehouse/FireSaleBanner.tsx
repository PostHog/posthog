import { useEffect, useRef, useState } from 'react'

import { dayjs } from 'lib/dayjs'

const endDate = dayjs.tz('2025-11-06T00:00:00Z', 'UTC')

function pad(n: number): string {
    return n.toString().padStart(2, '0')
}

export default function FireSaleBanner(): JSX.Element {
    const [now, setNow] = useState(dayjs())
    const intervalRef = useRef<number | null>(null)

    useEffect(() => {
        intervalRef.current = window.setInterval(() => setNow(dayjs()), 1000)
        return () => {
            if (intervalRef.current !== null) {
                window.clearInterval(intervalRef.current)
            }
        }
    }, [])

    const expired = now.isSameOrAfter(endDate)

    if (expired) {
        return <></>
    }

    const remainingMs = Math.max(0, endDate.diff(now))
    const totalSeconds = Math.floor(remainingMs / 1000)
    const days = Math.floor(totalSeconds / 86400)
    const hours = Math.floor((totalSeconds % 86400) / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60

    return (
        <div
            role="status"
            aria-live="polite"
            className="w-full bg-yellow-50 border-l-4 border-yellow-400 text-yellow-800 px-4 py-3 flex items-center justify-between gap-4"
        >
            <div className="flex items-center gap-3">
                <svg
                    className="h-5 w-5 text-yellow-600"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    aria-hidden
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3" />
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M12 20a8 8 0 100-16 8 8 0 000 16z"
                    />
                </svg>
                <span className="font-medium">Fire sale ends in</span>
            </div>

            <div className="flex items-center text-sm font-mono space-x-2">
                <div className="flex items-baseline gap-1">
                    <span className="px-2 py-1 bg-white border rounded text-black">{days}</span>
                    <span className="text-xs text-gray-600">d</span>
                </div>
                <div className="flex items-baseline gap-1">
                    <span className="px-2 py-1 bg-white border rounded text-black">{pad(hours)}</span>
                    <span className="text-xs text-gray-600">h</span>
                </div>
                <div className="flex items-baseline gap-1">
                    <span className="px-2 py-1 bg-white border rounded text-black">{pad(minutes)}</span>
                    <span className="text-xs text-gray-600">m</span>
                </div>
                <div className="flex items-baseline gap-1">
                    <span className="px-2 py-1 bg-white border rounded text-black">{pad(seconds)}</span>
                    <span className="text-xs text-gray-600">s</span>
                </div>
            </div>
        </div>
    )
}
