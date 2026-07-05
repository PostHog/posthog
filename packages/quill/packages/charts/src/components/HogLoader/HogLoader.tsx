import React from 'react'

const CSS = `
    @keyframes ph-ldr-spike {
        0%, 100% { transform: scaleY(1); }
        50% { transform: scaleY(1.15); }
    }
    .ph-ldr-spike {
        transform-box: fill-box;
        transform-origin: bottom center;
        animation: ph-ldr-spike 1.4s ease-in-out infinite;
    }
    .ph-ldr-blue   { animation-delay: 0ms; }
    .ph-ldr-red    { animation-delay: 180ms; }
    .ph-ldr-yellow { animation-delay: 360ms; }

    @keyframes ph-ldr-glow {
        0%, 100% { filter: drop-shadow(0 0 5px rgba(255, 255, 255, 0.12)); }
        50% { filter: drop-shadow(0 0 11px rgba(255, 255, 255, 0.3)); }
    }
    .ph-ldr-glow {
        animation: ph-ldr-glow 1.4s ease-in-out infinite;
    }

    @media (prefers-reduced-motion: reduce) {
        .ph-ldr-spike, .ph-ldr-glow { animation: none; }
    }
`

export interface HogLoaderProps {
    /** Width in px — height scales proportionally. Defaults to 64. */
    size?: number
    /** Desaturated, translucent rendering that sits into a skeleton instead of shouting over
     *  it. Also drops the glow (both effects animate `filter`, so they can't combine). */
    muted?: boolean
    className?: string
    style?: React.CSSProperties
}

/** Animated PostHog logo — spikes breathe in staggered sequence. */
export function HogLoader({ size = 64, muted = false, className, style }: HogLoaderProps): React.ReactElement {
    // viewBox: x -0.5→52, y -4.5→28.5 — extra headroom for scaleY(1.15) tip overshoot
    return (
        <svg
            width={size}
            height={Math.round((size * 33) / 52.5)}
            viewBox="-0.5 -4.5 52.5 33"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-label="Loading"
            role="img"
            className={[muted ? undefined : 'ph-ldr-glow', className].filter(Boolean).join(' ') || undefined}
            style={muted ? { filter: 'grayscale(0.25) opacity(0.7)', ...style } : style}
        >
            <style>{CSS}</style>
            <defs>
                {/* Blue spike — 3 gradient slices sharing one userSpaceOnUse gradient each */}
                <linearGradient id="ph-ldr-b1" x1="-5.33" y1="1.8" x2="10.58" y2="19.52" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#3F80FF" />
                    <stop offset="1" stopColor="#084FE0" />
                </linearGradient>
                <linearGradient id="ph-ldr-b2" x1="-4.88" y1="13.81" x2="8.63" y2="27.98" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#0255FF" />
                    <stop offset="1" stopColor="#0145D2" />
                </linearGradient>
                <linearGradient id="ph-ldr-b3" x1="-0.23" y1="18.94" x2="8.996" y2="28.27" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#0041C6" />
                    <stop offset="1" stopColor="#0045D0" />
                </linearGradient>
                {/* Red spike */}
                <linearGradient id="ph-ldr-r1" x1="10.55" y1="7.25" x2="21.74" y2="18.65" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#FF651E" />
                    <stop offset="1" stopColor="#E4400A" />
                </linearGradient>
                <linearGradient id="ph-ldr-r2" x1="10.43" y1="7.37" x2="22.44" y2="28.23" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#EF3C00" />
                    <stop offset="1" stopColor="#D63601" />
                </linearGradient>
                <linearGradient id="ph-ldr-r3" x1="10.13" y1="19.68" x2="16.4" y2="27.98" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#C42C00" />
                    <stop offset="1" stopColor="#D63600" />
                </linearGradient>
                {/* Yellow spike */}
                <linearGradient id="ph-ldr-y1" x1="21.69" y1="1.96" x2="33.1" y2="18.78" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#FFD849" />
                    <stop offset="0.956" stopColor="#FBAE01" />
                </linearGradient>
                <linearGradient id="ph-ldr-y2" x1="21.69" y1="7.97" x2="33.1" y2="27.93" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#FFB700" />
                    <stop offset="1" stopColor="#F9AA01" />
                </linearGradient>
                <linearGradient id="ph-ldr-y3" x1="21.84" y1="18.91" x2="30.76" y2="27.98" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#FF9500" />
                    <stop offset="1" stopColor="#F8AA00" />
                </linearGradient>
            </defs>

            {/* Blue spike — leftmost, tallest */}
            <g className="ph-ldr-spike ph-ldr-blue">
                <path d="M10.7401 7.14295L4.58711 0.815297C2.91642 -0.907781 0 0.279746 0 2.67808V7.50968L10.7401 18.733V7.14295Z" fill="url(#ph-ldr-b1)" />
                <path d="M10.74 18.725V28.0001H8.94141L0 18.1836V7.50946L10.74 18.725Z" fill="url(#ph-ldr-b2)" />
                <path d="M0 25.4097C0 26.8403 1.15978 28.0001 2.59044 28.0001H8.94531L0 18.18V25.4097Z" fill="url(#ph-ldr-b3)" />
            </g>

            {/* Red spike — middle */}
            <g className="ph-ldr-spike ph-ldr-red">
                <path d="M21.9693 7.64927L15.3273 0.815174C13.6567 -0.907902 10.7402 0.279623 10.7402 2.67796V7.14998L21.9693 18.6921V7.64927Z" fill="url(#ph-ldr-r1)" />
                <path d="M10.7402 7.14294V18.733L19.6001 28.0003H21.9693V18.6922L10.7402 7.14294Z" fill="url(#ph-ldr-r2)" />
                <path d="M10.7402 28.0003H19.6001L10.7402 18.733V28.0003Z" fill="url(#ph-ldr-r3)" />
            </g>

            {/* Yellow spike — closest to head */}
            <g className="ph-ldr-spike ph-ldr-yellow">
                <path d="M33.2915 19.2975V7.74241L26.5563 0.815175C24.8857 -0.907902 21.9692 0.279624 21.9692 2.67796V7.64998L33.2915 19.2917V19.2975Z" fill="url(#ph-ldr-y1)" />
                <path d="M21.9692 7.64935V18.6922L31.0154 28.0003H33.2915V19.29L21.9692 7.64935Z" fill="url(#ph-ldr-y2)" />
                <path d="M21.9692 28.0003H31.0154L21.9692 18.6922V28.0003Z" fill="url(#ph-ldr-y3)" />
            </g>

            {/* Head — static */}
            <path
                d="M50.01 23.3376L49.6723 23.2968C48.6653 23.1687 47.7281 22.7031 47.0179 21.9696L33.2856 7.74255V28.0003H48.9971C50.4757 28.0003 51.669 26.8012 51.669 25.3284V25.2236C51.669 24.2631 50.953 23.454 50.0041 23.3376H50.01ZM39.2 23.5471C38.2162 23.5471 37.4187 22.7496 37.4187 21.7658C37.4187 20.7821 38.2162 19.9845 39.2 19.9845C40.1838 19.9845 40.9813 20.7821 40.9813 21.7658C40.9813 22.7496 40.1838 23.5471 39.2 23.5471Z"
                fill="#111111"
            />
        </svg>
    )
}
