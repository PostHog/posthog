import React, { useEffect } from 'react'

export function useOnMountEffect(effect: React.EffectCallback): void {
    useEffect(effect, []) // oxlint-disable-line react-hooks/exhaustive-deps
}

export function useDelayedOnMountEffect(effect: () => void, timeout = 500): void {
    useOnMountEffect(() => {
        const timer = window.setTimeout(effect, timeout)
        return () => clearTimeout(timer)
    })
}
