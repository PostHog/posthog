import { useId } from 'react'

export interface PostHogLogoGradientAltProps {
    className?: string
    'aria-hidden'?: boolean | 'true' | 'false'
}

/** Redesigned PostHog logo — secondary gradient landscape lockup (no intersecting-gradient overlap). */
export function PostHogLogoGradientAlt({
    className,
    'aria-hidden': ariaHidden,
}: PostHogLogoGradientAltProps): JSX.Element {
    const u = useId().replace(/:/g, '')
    return (
        <svg
            className={className}
            width="52"
            height="28"
            viewBox="0 0 52 28"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden={ariaHidden}
        >
            <g clipPath={`url(#${u}clip0_56_954)`}>
                <path
                    d="M51.6612 25.2189C51.6612 24.2595 50.9444 23.451 49.9957 23.3324H50.0011L49.6616 23.2893C48.6537 23.16 47.7159 22.6964 47.0098 21.9634L33.282 7.74515V28H41.8086H48.9879C48.9879 28 48.9879 28 48.9932 28C49.8718 28 50.6479 27.5742 51.133 26.9221C51.23 26.7927 51.3109 26.6579 51.3863 26.5124C51.5642 26.1567 51.6612 25.7525 51.6612 25.3267V25.2243V25.2189ZM39.1946 23.5426C39.1623 23.5426 39.1353 23.5426 39.103 23.5426C38.1598 23.4941 37.416 22.718 37.416 21.764C37.416 21.058 37.8256 20.4435 38.4239 20.1579C38.6556 20.0447 38.9197 19.9854 39.1946 19.9854C40.1755 19.9854 40.9732 20.7831 40.9732 21.764C40.9732 22.745 40.1755 23.5426 39.1946 23.5426Z"
                    fill="#111111"
                />
                <path
                    d="M21.958 2.67334V7.62656C21.958 7.62656 21.958 7.62656 21.958 7.63195L33.2604 19.2308C33.2604 19.2308 33.2766 19.2308 33.2766 19.2254V7.75053C33.2766 7.75053 33.2766 7.75053 33.2766 7.74514L26.6256 0.846198C26.1028 0.301829 25.3805 0 24.6313 0C23.1545 0 21.958 1.19654 21.958 2.67334Z"
                    fill={`url(#${u}paint0_linear_56_954)`}
                />
                <path
                    d="M21.958 7.63193V18.681L31.029 28H33.2766V19.2469L21.958 7.63193Z"
                    fill={`url(#${u}paint1_linear_56_954)`}
                />
                <path d="M21.958 28H31.029L21.958 18.681V28Z" fill={`url(#${u}paint2_linear_56_954)`} />
                <path
                    d="M10.7419 2.66256V7.16304L21.9581 18.681V7.63195L15.3017 0.80308C14.8005 0.291049 14.116 0 13.4045 0C11.9331 0 10.7419 1.19115 10.7419 2.66256Z"
                    fill={`url(#${u}paint3_linear_56_954)`}
                />
                <path d="M10.7419 28H19.6998L10.7419 18.6757V28Z" fill={`url(#${u}paint4_linear_56_954)`} />
                <path
                    d="M10.7419 7.16302V18.6756L19.6998 28H19.7052H21.9581V18.681L10.7419 7.16302Z"
                    fill={`url(#${u}paint5_linear_56_954)`}
                />
                <path
                    d="M10.7419 7.16304L4.53821 0.7923C4.04235 0.285659 3.36862 0 2.66256 0C1.19115 0 0 1.19115 0 2.66256V7.5026L10.7419 18.681V7.16304Z"
                    fill={`url(#${u}paint6_linear_56_954)`}
                />
                <path
                    d="M9.1896 28H10.7419V18.6756L0 7.50259V18.2283L9.1896 28Z"
                    fill={`url(#${u}paint7_linear_56_954)`}
                />
                <path
                    d="M0 25.4129C0 26.8412 1.15881 27.9946 2.58171 27.9946H9.1896L0 18.2283V25.4129Z"
                    fill={`url(#${u}paint8_linear_56_954)`}
                />
            </g>
            <defs>
                <linearGradient
                    id={`${u}paint0_linear_56_954`}
                    x1="21.958"
                    y1="9.6154"
                    x2="33.2766"
                    y2="9.6154"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#FFD849" />
                    <stop offset="0.96" stopColor="#FBAE01" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint1_linear_56_954`}
                    x1="21.958"
                    y1="17.8133"
                    x2="33.2766"
                    y2="17.8133"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#FFB700" />
                    <stop offset="1" stopColor="#F9AA01" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint2_linear_56_954`}
                    x1="21.958"
                    y1="23.3378"
                    x2="31.029"
                    y2="23.3378"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#FF9500" />
                    <stop offset="1" stopColor="#F8AA00" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint3_linear_56_954`}
                    x1="10.7419"
                    y1="9.34052"
                    x2="21.9581"
                    y2="9.34052"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#FF651E" />
                    <stop offset="1" stopColor="#E4400A" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint4_linear_56_954`}
                    x1="10.7419"
                    y1="23.3378"
                    x2="19.6998"
                    y2="23.3378"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#C42C00" />
                    <stop offset="1" stopColor="#D63600" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint5_linear_56_954`}
                    x1="10.7419"
                    y1="17.5815"
                    x2="21.9581"
                    y2="17.5815"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#EF3C00" />
                    <stop offset="1" stopColor="#D63601" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint6_linear_56_954`}
                    x1="0"
                    y1="9.34052"
                    x2="10.7419"
                    y2="9.34052"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#3F80FF" />
                    <stop offset="1" stopColor="#084FE0" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint7_linear_56_954`}
                    x1="0"
                    y1="17.7486"
                    x2="10.7419"
                    y2="17.7486"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#0255FF" />
                    <stop offset="1" stopColor="#0145D2" />
                </linearGradient>
                <linearGradient
                    id={`${u}paint8_linear_56_954`}
                    x1="0"
                    y1="23.1115"
                    x2="9.1896"
                    y2="23.1115"
                    gradientUnits="userSpaceOnUse"
                >
                    <stop stopColor="#0041C6" />
                    <stop offset="1" stopColor="#0045D0" />
                </linearGradient>
                <clipPath id={`${u}clip0_56_954`}>
                    <rect width="51.6748" height="28" fill="white" />
                </clipPath>
            </defs>
        </svg>
    )
}
