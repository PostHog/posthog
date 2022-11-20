import { RefObject, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import ResizeObserver from 'resize-observer-polyfill'

export interface FitTextProps {
    maxFontSize?: number
    minFontSize?: number
    onFinish?: (fontSize: number) => void
    onStart?: () => void
    resolution?: number
    text?: string
}

export interface FitTextResult {
    fontSize: string
    ref: RefObject<HTMLDivElement>
}

/** based on https://github.com/saltycrane/use-fit-text **/
const useFitText = ({
    text,
    maxFontSize = 100,
    minFontSize = 14,
    onFinish,
    onStart,
    resolution = 5,
}: FitTextProps = {}): FitTextResult => {
    const initState = useCallback(() => {
        return {
            calcKey: 0,
            fontSize: Math.floor(maxFontSize),
            fontSizePrev: minFontSize,
            fontSizeMax: maxFontSize,
            fontSizeMin: minFontSize,
            finishedSeeking: false,
        }
    }, [maxFontSize, minFontSize])

    const ref = useRef<HTMLDivElement>(null)
    const isCalculatingRef = useRef(false)
    const [state, setState] = useState(initState)
    const { calcKey, fontSize, fontSizeMax, fontSizeMin, fontSizePrev, finishedSeeking } = state
    const [existingText, setExistingText] = useState(text)
    const [candidateSizes, setCandidateSizes] = useState<Set<number>>(new Set([]))

    useEffect(() => {
        if (text !== existingText) {
            setExistingText(text)
        }
    })

    let animationFrameId: number | null = null
    const [ro] = useState(
        () =>
            new ResizeObserver(() => {
                animationFrameId = window.requestAnimationFrame(() => {
                    if (isCalculatingRef.current) {
                        return
                    }
                    onStart && onStart()
                    isCalculatingRef.current = true
                    // `calcKey` is used in the dependencies array of
                    // `useLayoutEffect` below. It is incremented so that the font size
                    // will be recalculated even if the previous state didn't change (e.g.
                    // when the text fit initially).
                    setState({
                        ...initState(),
                        calcKey: calcKey + 1,
                    })
                })
            })
    )

    useEffect(() => {
        if (ref.current) {
            ro.observe(ref.current)
        }
        return () => {
            animationFrameId && window.cancelAnimationFrame(animationFrameId)
            ro.disconnect()
        }
    }, [animationFrameId, ro])

    // Recalculate when the text changes
    useEffect(() => {
        if (calcKey === 0 || isCalculatingRef.current) {
            return
        }

        onStart && onStart()
        setState({
            ...initState(),
            calcKey: calcKey + 1,
        })
    }, [text])

    useLayoutEffect(() => {
        // Don't start calculating font size until the `resizeKey` is incremented
        // above in the `ResizeObserver` callback. This avoids an extra resize
        // on initialization.
        if (calcKey === 0 || finishedSeeking) {
            return
        }

        const isFinishedSeekingNow = !ref.current || Math.abs(fontSize - fontSizePrev) <= resolution
        const isOverflow =
            !!ref.current &&
            (ref.current.scrollHeight > ref.current.offsetHeight || ref.current.scrollWidth > ref.current.offsetWidth)
        const isFailed = isOverflow && fontSize === minFontSize
        const isAsc = fontSize > fontSizePrev

        if (!isOverflow) {
            // track the found non-overflowing font sizes
            setCandidateSizes(new Set([...Array.from(candidateSizes).filter((c) => c < fontSize), fontSize]))
        }

        if (finishedSeeking || isFinishedSeekingNow) {
            isCalculatingRef.current = false
            if (isOverflow && !isFailed) {
                // has finished seeking but is still overflowing
                // reduces font size to an earlier increment that didn't overflow
                // or a guess at a candidate.
                const useEarlierCandidate =
                    candidateSizes.size > 1 && fontSize === Array.from(candidateSizes)[candidateSizes.size - 1]
                const adjustedFontSize = useEarlierCandidate
                    ? candidateSizes[candidateSizes.size - 2]
                    : fontSize - resolution

                setState({
                    fontSize: adjustedFontSize,
                    // reset max and min or you can get stuck flapping
                    fontSizeMax: Math.min(
                        adjustedFontSize + resolution,
                        candidateSizes.size ? Array.from(candidateSizes)[candidateSizes.size - 1] : maxFontSize
                    ),
                    fontSizeMin: Math.max(minFontSize, adjustedFontSize - resolution),
                    fontSizePrev,
                    calcKey,
                    finishedSeeking: true,
                })
            } else {
                setState({
                    fontSize: fontSize,
                    // reset max and min or you can get stuck flapping
                    fontSizeMax: fontSizeMax,
                    fontSizeMin: fontSizeMin,
                    fontSizePrev,
                    calcKey,
                    finishedSeeking: true,
                })
            }
            if (!isCalculatingRef.current && candidateSizes.size) {
                const candidate = Array.from(candidateSizes)[candidateSizes.size - 1]
                onFinish?.(candidate)
            }
        } else {
            // Binary search to adjust font size
            let delta: number
            let newMax = fontSizeMax
            let newMin = fontSizeMin
            if (isOverflow) {
                delta = isAsc ? fontSizePrev - fontSize : fontSizeMin - fontSize
                newMax = Math.min(fontSizeMax, fontSize)
            } else {
                delta = isAsc ? fontSizeMax - fontSize : fontSizePrev - fontSize
                newMin = Math.max(fontSizeMin, fontSize)
            }

            const nextState = {
                calcKey,
                fontSize: Math.floor(fontSize + delta / 2),
                fontSizeMax: newMax,
                fontSizeMin: newMin,
                fontSizePrev: fontSize,
                finishedSeeking: finishedSeeking,
            }

            setState(nextState)
        }
    }, [calcKey, fontSize, fontSizeMax, fontSizeMin, fontSizePrev, onFinish, ref, resolution])

    return {
        fontSize: `${isCalculatingRef.current ? fontSize : Array.from(candidateSizes)[candidateSizes.size - 1]}px`,
        ref,
    }
}

export default useFitText
