import './AnimatedSparkles.scss'

interface SparkleProps {
    size?: number
    className?: string
    delay?: number
}

function Sparkle({ size = 14, className = '', delay = 0 }: SparkleProps): JSX.Element {
    return (
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
}

interface AnimatedSparklesProps {
    className?: string
    triggerAnimation?: boolean
}

export function AnimatedSparkles({ className = '', triggerAnimation = false }: AnimatedSparklesProps): JSX.Element {
    return (
        <div className={`sparkles-container ${triggerAnimation ? 'animate' : ''} ${className}`}>
            <Sparkle key={0} size={5} delay={300} className="sparkle sparkle--small" />
            <Sparkle key={1} size={8} delay={150} className="sparkle sparkle--medium" />
            <Sparkle key={2} size={13} delay={0} className="sparkle sparkle--large" />
        </div>
    )
}

export default AnimatedSparkles
