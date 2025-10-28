import './AnimatedSparkles.scss'

import React from 'react'

interface SparkleProps {
    fill?: string
    size?: number
    className?: string
    delay?: number
}

const Sparkle: React.FC<SparkleProps> = ({ size = 14, className = '', delay = 0 }) => (
    <svg
        width={size}
        height={size + 1}
        viewBox="0 0 14 15"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={`sparkle ${className} fill-accent dark:fill-white`}
        style={{
            animationDelay: `${delay}ms`,
        }}
    >
        <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M7 0C7 0 6.49944 2.07875 6.08971 3.78113C5.76569 5.12694 4.77707 6.17975 3.50849 6.5303C1.9232 6.96825 0 7.50005 0 7.50005C0 7.50005 1.9232 8.03143 3.50849 8.46949C4.77707 8.82025 5.76569 9.87317 6.08971 11.2189C6.49944 12.9214 7 15 7 15C7 15 7.50056 12.9214 7.91029 11.2189C8.23441 9.87317 9.22293 8.82025 10.4918 8.46949C12.0769 8.03143 14 7.50005 14 7.50005C14 7.50005 12.0769 6.96825 10.4918 6.5303C9.22293 6.17975 8.23441 5.12694 7.91029 3.78113C7.50056 2.07875 7 0 7 0Z"
            fill="inherit"
        />
    </svg>
)

interface AnimatedSparklesProps {
    className?: string
    sparkleColors?: string[]
    sparkleCount?: number
    triggerAnimation?: boolean
}

export const AnimatedSparkles: React.FC<AnimatedSparklesProps> = ({ className = '', triggerAnimation = false }) => {
    const sparkles = [
        { id: 0, delay: 300, size: 5, position: 'small' },
        { id: 1, delay: 150, size: 8, position: 'medium' },
        { id: 2, delay: 0, size: 13, position: 'large' },
    ]

    return (
        <div className={`sparkles-container ${triggerAnimation ? 'animate' : ''} ${className}`}>
            {sparkles.map((sparkle) => (
                <Sparkle
                    key={sparkle.id}
                    size={sparkle.size}
                    delay={sparkle.delay}
                    className={`sparkle sparkle--${sparkle.position}`}
                />
            ))}
        </div>
    )
}

export default AnimatedSparkles
