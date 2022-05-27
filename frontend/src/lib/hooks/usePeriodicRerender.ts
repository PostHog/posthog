import { useEffect, useState } from 'react'

export function usePeriodicRerender(milliseconds: number): void {
    const [, setTick] = useState(0)

    useEffect(() => {
        const intervalId = setInterval(() => setTick((state) => state + 1), milliseconds)
        return () => clearInterval(intervalId)
    })
}
