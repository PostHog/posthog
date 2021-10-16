import React, { useRef } from 'react'

enum SectionType {
    INACTIVE = 'inactive',
    DEFAULT = 'default',
}

interface RangeSection {
    start: number
    end: number
    type: SectionType
}

interface SliderProps {
    value: number
    total: number
    onChange: (value: number) => void
    buffered?: number
    sections?: RangeSection[]
}

const getPercentage = (current: number, max: number): number => (100 * current) / max

export function Slider({}: /*value, total, onChange, buffered = 0, sections = [] */ SliderProps): JSX.Element {
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
        thumbRef.current.style.left = `calc(${newPercentage}%)`
    }

    const handleMouseUp = (): void => {
        document.removeEventListener('mouseup', handleMouseUp)
        document.removeEventListener('mousemove', handleMouseMove)
    }

    const handleMouseDown = (event: React.MouseEvent<HTMLDivElement, MouseEvent>): void => {
        if (!thumbRef.current) {
            return
        }

        diff.current = event.clientX - thumbRef.current.getBoundingClientRect().left

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
        <div
            className="slider"
            ref={sliderRef}
            onClick={handleClick}
            style={{
                width: '100%',
                height: 12,
                position: 'relative',
            }}
        >
            <div
                className="filled-slider"
                style={{
                    backgroundColor: 'green',
                    width: '100%',
                    top: 5,
                    height: 2,
                    borderRadius: 4,
                    position: 'relative',
                }}
            />
            <div
                className="thumb"
                ref={thumbRef}
                style={{
                    top: -2,
                    position: 'relative',
                    borderRadius: '50%',
                    width: 12,
                    height: 12,
                    border: '2px solid #0F0F0F',
                    backgroundColor: 'transparent',
                }}
                onMouseDown={handleMouseDown}
            />
            <div className="current-bar" style={{ position: 'relative' }} />
            <div className="buffer-bar" style={{ position: 'relative' }} />
        </div>
    )
}
