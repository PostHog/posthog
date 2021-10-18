import React, { useRef } from 'react'
import './Slider.scss'

// enum SectionType {
//     INACTIVE = 'inactive',
//     DEFAULT = 'default',
// }

// interface RangeSection {
//     start: number
//     end: number
//     type: SectionType
// }

// interface SliderProps {
//     value: number
//     total: number
//     onChange: (value: number) => void
//     buffered?: number
//     sections?: RangeSection[]
// }

const getPercentage = (current: number, max: number): number => (100 * current) / max

export function Slider(/* {value, total, onChange, buffered = 0, sections = [] }: SliderProps */): JSX.Element {
    const sliderRef = useRef<HTMLDivElement | null>(null)
    const thumbRef = useRef<HTMLDivElement | null>(null)

    const diff = useRef<number>()

    const handleMouseMove = (event: MouseEvent): void => {
        if (!diff.current || !sliderRef.current || !thumbRef.current) {
            return
        }

        let newX = event.clientX - diff.current - sliderRef.current.getBoundingClientRect().left

        const end = sliderRef.current.offsetWidth
        newX = Math.max(Math.min(newX, end), 0)
        const newPercentage = getPercentage(newX, end)
        thumbRef.current.style.left = `calc(${newPercentage}% - 6px)`
    }

    const handleMouseUp = (): void => {
        document.removeEventListener('mouseup', handleMouseUp)
        document.removeEventListener('mousemove', handleMouseMove)
    }

    const handleMouseDown = (event: React.MouseEvent<HTMLDivElement, MouseEvent>): void => {
        if (!thumbRef.current) {
            return
        }

        diff.current = event.clientX - thumbRef.current.getBoundingClientRect().left - 6

        document.addEventListener('mousemove', handleMouseMove)
        document.addEventListener('mouseup', handleMouseUp)
    }

    const handleClick = (event: React.MouseEvent<HTMLDivElement, MouseEvent>): void => {
        if (!thumbRef.current || !sliderRef.current) {
            return
        }
        // jump thumb to click position
        let newX = event.clientX - sliderRef.current.getBoundingClientRect().left
        const end = sliderRef.current.offsetWidth
        newX = Math.max(Math.min(newX, end), 0)
        const newPercentage = getPercentage(newX, end)
        thumbRef.current.style.left = `calc(${newPercentage}% - 6px)`
    }

    // const currentPercent = value / total
    // const bufferPercent = Math.max(buffered, value) / total

    return (
        <div className="rrweb-controller-slider" ref={sliderRef} onClick={handleClick}>
            <div className="slider" />
            <div className="thumb" ref={thumbRef} onMouseDown={handleMouseDown} />
            <div className="current-bar" />
            <div className="buffer-bar" />
        </div>
    )
}
