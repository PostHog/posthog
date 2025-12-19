import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { isChristmas } from 'lib/holidays'

const LogomarkHead = ({ children }: { children?: React.ReactNode }): JSX.Element => (
    <g id="head" className="fill-[var(--brand-key)] dark:fill-white">
        <path d="M903.1641,358.57729l-110.00034,-124.75323c-7.36453,-8.35223 -19.98943,-2.38637 -19.98943,9.41282v174.60152c0,7.29164 5.26039,13.25752 11.68974,13.25752h170.43622c6.42935,0 11.68972,-5.96588 11.68972,-13.25752v-15.90902c0,-7.29164 -5.26037,-13.12495 -11.68972,-14.05298c-19.63875,-2.91665 -37.99162,-13.12493 -52.13618,-29.16653zM829.16811,388.53929c-10.28695,0 -18.70356,-9.54543 -18.70356,-21.21203c0,-11.66661 8.41661,-21.21202 18.70356,-21.21202c10.28695,0 18.70356,9.54541 18.70356,21.21202c0,11.66661 -8.41661,21.21203 -18.70356,21.21203z" />
        {children}
    </g>
)

const LogomarkChristmasHat = (): JSX.Element => (
    <g id="christmas-hat">
        <path
            d="M760.44221,350.78547l105.09131,-63.59165c2.99786,-1.81373 3.53866,-6.05832 1.09756,-8.61203l-74.51149,-77.93921c-8.68281,-9.08152 -23.24768,-7.66116 -30.12961,2.93974l-42.29777,65.15048c-2.27949,3.511 2.05301,7.56212 5.21072,4.87178l27.51804,-23.44101v95.87485c0,4.25098 4.47015,6.8964 8.02125,4.74706z"
            className="fill-[var(--brand-red)]"
            stroke="none"
            stroke-width="1"
        />
        <path
            d="M748.13994,352.44425v-32.45923c0,-2.87648 1.45099,-5.54575 3.82903,-7.04497l91.41712,-57.60028c3.09288,-1.94944 7.06755,-1.50563 9.68623,1.07927l23.26986,22.977c3.87165,3.8228 3.07691,10.41935 -1.58416,13.14544l-114.68697,67.08341c-5.32797,3.11581 -11.93107,-0.85826 -11.93107,-7.18066z"
            fill="#ffffff"
            stroke="#000000"
            stroke-width="5"
        />
        <path
            d="M745.94127,261.57323c0,8.54877 -6.71144,15.47909 -14.99021,15.47909c-8.27877,0 -14.99019,-6.93033 -14.99019,-15.47909c0,-8.54877 6.71142,-15.47909 14.99019,-15.47909c8.27877,0 14.99021,6.93033 14.99021,15.47909z"
            fill="#ffffff"
            stroke="#000000"
            stroke-width="5"
        />
    </g>
)

export function Logomark(): JSX.Element {
    return (
        <svg
            width="45"
            height="25"
            viewBox="406 78.49999 560.99001 352.59593"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            <g id="blue" className="fill-[var(--brand-blue)] dark:fill-white">
                <path d="M425.98943,347.57356c-7.36453,-8.35223 -19.98943,-2.38635 -19.98943,9.41284v60.71942c0,7.29164 5.26037,13.25754 11.68972,13.25754h53.53895c5.26037,0 9.118,-3.57953 10.75456,-8.21967c0.46758,-1.19318 0.70139,-2.38635 0.81829,-3.57953c0.35069,-3.71211 -0.5845,-7.68937 -3.39003,-10.87117l-53.53895,-60.71944z" />
                <path d="M425.98943,214.99838c-7.36453,-8.35223 -19.98943,-2.38635 -19.98943,9.41284v68.54137c0,3.57953 1.28587,6.89391 3.39003,9.41284l110.00032,124.75323l3.39003,3.84469v-106.06015z" />
                <path d="M425.98943,82.42319c-7.36453,-8.35223 -19.98943,-2.38635 -19.98943,9.41284v68.54137c0,3.57953 1.28587,6.89391 3.39003,9.41284l113.39035,128.59793v0v-106.06015z" />
            </g>
            <g id="red" className="fill-[var(--brand-red)] dark:fill-white">
                <path d="M596.42565,408.293l-73.52838,-83.38979v106.06015h65.22867c10.40385,0 15.66424,-14.31813 8.29971,-22.67036z" />
                <path d="M636.28762,321.05853l-113.39035,-128.73051v16.43933v73.18149v11.00375v5.43558l3.39003,3.84468l110.00032,124.75325l3.39003,3.97726v-1.32576v-99.29881v-5.43558z" />
                <path d="M636.28762,188.48334l-8.6504,-9.81057l-84.86741,-96.24958c-0.93518,-1.06059 -1.87035,-1.85606 -2.92243,-2.51894c-2.10416,-1.19318 -4.4421,-1.59089 -6.54626,-1.32574c-2.22105,0.26515 -4.32521,1.32576 -6.07866,2.78408c-0.81829,0.79544 -1.63654,1.72347 -2.33793,2.78406c-1.28587,2.1212 -2.10416,4.64014 -2.10416,7.55679v68.54137c0,3.57953 1.28587,6.89391 3.39003,9.41284l113.39035,128.59793v-106.06013l-3.39003,-3.84469z" />
            </g>
            <g id="yellow" className="fill-[var(--brand-yellow)] dark:fill-white">
                <path d="M713.32292,408.293l-73.52838,-83.38979v106.06015h65.22867c10.40385,0 15.66424,-14.31813 8.29971,-22.67036z" />
                <path d="M639.67765,298.38817v-106.06015l113.39035,128.59793c2.22105,2.51894 3.39003,5.83331 3.39003,9.41284v68.54137c0,11.79919 -12.6249,17.76507 -19.98943,9.41284l-96.90784,-109.90483z" />
                <path d="M753.18489,188.48334l-93.51781,-106.06015c-7.36453,-8.35223 -19.98943,-2.38635 -19.98943,9.41284v68.54137c0,3.57953 1.28587,6.89391 3.39003,9.41284l93.51781,106.06015c7.36453,8.35223 19.98943,2.38635 19.98943,-9.41284v-68.54137c0,-3.57953 -1.28587,-6.89391 -3.39003,-9.41284z" />
            </g>

            <LogomarkHead>{isChristmas() && <LogomarkChristmasHat />}</LogomarkHead>
        </svg>
    )
}

export interface AnimatedLogomarkProps {
    /** Animate the logomark continuously (e.g. during loading states) */
    animate: boolean
    /** Play a single animation cycle and call the provided callback when done */
    animateOnce?: () => void
    className?: string
}

/**
 * Animated PostHog logomark that jumps continuously while `animate` is true.
 *
 * When `animate` becomes false, the animation completes its current cycle before
 * stopping - it won't cut off mid-jump.
 *
 * When `animateOnce` is provided, plays a single animation cycle and calls
 * the provided callback when done.
 */
export function AnimatedLogomark({ animate, animateOnce, className }: AnimatedLogomarkProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const [isAnimating, setIsAnimating] = useState(false)
    const shouldStopRef = useRef(false)
    const animateOnceRef = useRef(animateOnce)

    animateOnceRef.current = animateOnce

    // Track stop intent via ref so the listener always sees current value
    // without needing to be re-attached when `animate` changes
    shouldStopRef.current = !animate && isAnimating

    // Start animation immediately when requested
    useEffect(() => {
        if (animate || animateOnce) {
            setIsAnimating(true)
        }
    }, [animate, animateOnce])

    // Set up iteration listener once when animation starts.
    // The listener checks shouldStopRef on each cycle to decide whether to stop.
    useEffect(() => {
        if (!isAnimating || !ref.current) {
            return
        }

        const animatedElement = ref.current.querySelector('svg > *')
        if (!animatedElement) {
            return
        }

        const handleAnimationIteration = (): void => {
            if (animateOnceRef.current) {
                setIsAnimating(false)
                animateOnceRef.current()
            } else if (shouldStopRef.current) {
                setIsAnimating(false)
            }
        }

        animatedElement.addEventListener('animationiteration', handleAnimationIteration)
        return () => {
            animatedElement.removeEventListener('animationiteration', handleAnimationIteration)
        }
    }, [isAnimating])

    return (
        <div ref={ref} className={clsx(className, isAnimating && 'animate-logomark-jump-continuous')}>
            <Logomark />
        </div>
    )
}
