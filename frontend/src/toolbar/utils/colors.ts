import { CSSProperties } from 'react'

export function getBoxColors(color: 'blue' | 'red' | 'green', hover = false, opacity = 0.2): CSSProperties | undefined {
    if (color === 'blue') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(240, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(240, 90%, 27%, 0.2) 0px 3px 10px ${hover ? 4 : 0}px`,
            outline: `hsla(240, 90%, 58%, 0.5) solid 1px`,
        }
    }
    if (color === 'red') {
        return {
            backgroundBlendMode: 'multiply',
            background: `hsla(4, 90%, 58%, ${opacity})`,
            boxShadow: `hsla(4, 90%, 27%, 0.2) 0px 3px 10px ${hover ? 5 : 0}px`,
            outline: `hsla(4, 90%, 58%, 0.5) solid 1px`,
        }
    }
}

export function getHeatMapHue(count: number, maxCount: number): number {
    if (maxCount === 0) {
        return 60
    }
    return 60 - (count / maxCount) * 40
}
